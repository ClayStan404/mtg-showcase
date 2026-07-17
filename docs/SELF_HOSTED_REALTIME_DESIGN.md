# Self-Hosted Realtime Read Path — Design Document

**Status:** Proposed (not implemented)  
**Date:** 2026-07-17  
**Target scale:** ~100 sellers, ~2000 daily buyer visitors (DAU)  
**Audience:** Maintainers implementing a future migration off GitHub Pages + snapshot CDN  

---

## 1. Problem statement

Today (Scheme C):

- **Writes** go to Supabase in real time (admin SPA).
- **Public reads** use rebuilt JSON snapshots on Supabase Storage (and GitHub Pages for the shell).
- Sync is a **full catalog rebuild** (export → Scryfall/mtgch enrich → upload), typically ~1 minute after save (debounced) or hourly cron.

Pain points:

1. Buyer-facing lists lag behind admin edits (build + enrich, not millisecond-fresh).
2. Full rebuild cost grows with catalog size even when one row changes.
3. Operational path is split across GitHub Actions, Storage, and Pages.

Goal of this design: **move frontend + API + Postgres onto a single (or small) self-hosted stack**, with **paginated real-time reads** from the database, while keeping **image hotlinks** on external CDNs and preserving product behavior (no in-site checkout).

Non-goals:

- Hosting card images on our servers.
- In-site payment / escrow.
- Full-text multi-language search engines (Postgres is enough at this scale).
- Replacing Scryfall/mtgch as metadata authorities (they remain enrichment sources).

---

## 2. Recommended approach (summary)

| Layer | Choice |
|-------|--------|
| Public UI | Same vanilla SPA (or lightly adapted) served by Nginx |
| Admin UI | Same admin SPA, talking to our API instead of Supabase JS |
| API | Small HTTP service (prefer **Go** or **Python FastAPI**; language open) |
| Database | **Postgres 16** (same schema spirit as current Supabase tables) |
| Auth | JWT sessions (Postgres `users` + bcrypt, or reverse-proxy OIDC later) |
| Cache | Optional **Redis** or in-process TTL cache for hot list queries |
| Images | Hotlink Scryfall / mtgch CDN only |
| Enrichment | Background worker (same logic as `build_common.py`) fills `card_printings` |
| Deploy | Docker Compose on one VPS (start); split DB later if needed |
| Hosting size (target scale) | **2 vCPU / 4 GB RAM / 5–10 Mbps / 40 GB SSD** |

**Core idea:** write path is transactional to Postgres; read path is **SQL with pagination + filters**, not full-catalog JSON download. Enrichment is **async and cached per printing**, not per pageview.

---

## 3. Current vs target architecture

### 3.1 Current (Scheme C)

```
Browser ──► GitHub Pages (HTML/JS)
              │ fetch
              ▼
         Storage cards.json (full snapshot)
              │
Admin ──► Supabase Auth + Postgres
              │
         Actions: export → Scryfall/mtgch → rebuild snapshot → upload
```

### 3.2 Target (this design)

```
                    ┌──────────── Nginx ────────────┐
Buyer ─────────────►│  static UI (index + assets)   │
                    │  /api/*  → API service        │
Seller ────────────►│  /admin  static + /api/*      │
                    └───────────┬──────────────────┘
                                │
                    ┌───────────▼──────────────────┐
                    │  API (auth, CRUD, list APIs) │
                    │  optional Redis list cache   │
                    └───────────┬──────────────────┘
                                │
                    ┌───────────▼──────────────────┐
                    │  Postgres                    │
                    │  users, profiles, inventory, │
                    │  wants, card_printings       │
                    └───────────┬──────────────────┘
                                │
                    ┌───────────▼──────────────────┐
                    │  Enrichment worker           │
                    │  (Scryfall + mtgch, disk     │
                    │   cache, queue on write)     │
                    └──────────────────────────────┘
                              │
                    Browser still loads images from
                    cards.scryfall.io / images.mtgch.com
```

---

## 4. Scale assumptions & capacity

| Parameter | Assumption |
|-----------|------------|
| Sellers | 100 |
| Cards per seller (avg) | 200–500 → **20k–50k** inventory rows |
| Buyer DAU | 2000 |
| Peak concurrent buyers | ~50–100 (not 2000) |
| List page size | **60** (match current `PAGE_SIZE`) |
| Avg list API payload | **50–200 KB** gzip after pagination |
| Image traffic | **External CDN** (not on our host) |

Rough load:

- List API: ~3k–10k requests/day → average **&lt; 0.2 QPS**, peak **1–5 QPS** with margin.
- Seller writes: sparse (batch import occasional spikes).

**Sizing conclusion:** one small VPS is enough if lists are paginated. Full-table JSON per pageview is **rejected** for this design.

---

## 5. Data model

Keep conceptual compatibility with current Supabase schema; add a printing cache table for enriched display fields.

### 5.1 Tables

**`users`** (auth)

| Column | Notes |
|--------|--------|
| `id` UUID PK | |
| `email` unique | |
| `password_hash` | or external IdP subject later |
| `created_at` | |

**`profiles`** (same role as today)

| Column | Notes |
|--------|--------|
| `id` UUID PK = `users.id` | |
| `seller_name`, `city`, `contact` | required for public listing |
| timestamps | |

**`inventory`**

| Column | Notes |
|--------|--------|
| `id` UUID PK | |
| `seller_id` → profiles | RLS/owner rules in API |
| `set_code`, `number`, `lang`, `foil` | |
| `quantity`, `price`, `note` | same conventions as now |
| unique (seller_id, set, number, lang, foil, price, note) | match current uniqueness |

**`wants`**

Symmetric to inventory with `buyer_id`, `must`, etc.

**`card_printings`** (new — enrichment cache)

| Column | Notes |
|--------|--------|
| PK `(set_code, number, lang)` | printing identity |
| `name_en`, `name_zh`, `name_printed` | |
| `type_line`, `type_line_en`, `types[]` or JSON | |
| `mana_cost`, `cmc`, `text` | |
| `image_small`, `image_normal`, `image_large` | hotlink URLs only |
| `image_lang` | face language of art |
| `scryfall_uri` | optional |
| `enriched_at`, `error` | |
| `source` | `scryfall` / `mtgch` / mix |

Public list queries **JOIN** inventory/wants → profiles → `card_printings`.  
Missing enrichment: return row with empty images + flag; worker fills shortly (admin already has live Scryfall/mtgch preview).

### 5.2 Indexes (minimum)

- `inventory (seller_id)`, `(set_code, number)`, `(lang)`, `(city via join — denormalize city on inventory optional)`  
- For filters used today: seller nickname, city, lang, foil, type (via printing), cmc range  
- Full-text: Postgres `tsvector` on `name_en || name_zh || note` if needed; start with `ILIKE` + trigram (`pg_trgm`) at 50k rows.

### 5.3 Migration from Supabase

1. `pg_dump` or existing `backup_supabase.py` logical dump.  
2. Import users/profiles/inventory/wants.  
3. Run enrichment worker over distinct `(set, number, lang)` (reuse `.cache/scryfall` logic from `build_common.py`).  
4. Dual-run period optional: keep Scheme C until API parity.

---

## 6. API design

Base path: `/api/v1`. JSON. Auth: `Authorization: Bearer <access_token>` for write routes; public list routes unauthenticated.

### 6.1 Public (buyers)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/listings` | Paginated sell list |
| `GET` | `/wants` | Paginated want list |
| `GET` | `/meta/filters` | Distinct sellers, cities, langs for filter UI |
| `GET` | `/healthz` | Liveness |

**`GET /listings` query params**

| Param | Default | Notes |
|-------|---------|--------|
| `page` | 1 | 1-based |
| `page_size` | 60 | max 100 |
| `q` | | search string |
| `seller` | all | nickname or id |
| `city` | all | |
| `lang` | all | en/zhs/ja/other |
| `foil` | all | |
| `type` | all | creature/… |
| `cmc` | all | |
| `sort` | `updated_desc` | limited enum |

**Response shape** (compatible with current card object fields so `mtg-ui.js` needs minimal change):

```json
{
  "page": 1,
  "page_size": 60,
  "total": 1234,
  "items": [
    {
      "id": "uuid",
      "set": "pip",
      "number": "717",
      "lang": "zhs",
      "lang_label": "简中",
      "foil": false,
      "quantity": 1,
      "price": 0,
      "note": "",
      "seller": "nick",
      "seller_id": "uuid",
      "city": "武汉",
      "contact": "…",
      "name_en": "…",
      "name_zh": "…",
      "image": { "small": "…", "normal": "…", "large": "…" },
      "image_lang": "zhs",
      "types": ["instant"],
      "mana_cost": "…",
      "cmc": 2
    }
  ]
}
```

Same pattern for `/wants`.

### 6.2 Authenticated (sellers/buyers)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/auth/login` | email + password → tokens |
| `POST` | `/auth/logout` | invalidate refresh |
| `GET` | `/me` | user + profile |
| `PATCH` | `/me/profile` | nickname/city/contact |
| `GET/POST/PATCH/DELETE` | `/me/inventory` | CRUD own stock |
| `POST` | `/me/inventory/batch` | bulk upsert (import) |
| `GET/POST/PATCH/DELETE` | `/me/wants` | CRUD own wants |

On write to inventory/wants:

1. Validate ownership.  
2. Upsert row.  
3. Enqueue enrichment job for `(set_code, number, lang)` if missing/stale in `card_printings`.  
4. Invalidate list cache keys (if Redis).

**No “publish” button required** for public visibility — commit is the publish. Optional “refresh enrichment” button for stuck printings.

### 6.3 Admin vs public CSP

- `connect-src` includes own API origin only (plus Scryfall/mtgch if admin still does client-side preview).  
- Prefer **server-side** enrichment preview via `GET /api/v1/printings/{set}/{number}?lang=` to avoid browser CORS/CSP sprawl.

---

## 7. Enrichment worker

Port logic from `scripts/build_common.py` into a long-running worker (or CLI invoked by systemd timer as interim).

| Concern | Behavior |
|---------|----------|
| Trigger | Queue on inventory/wants write; periodic sweep for `enriched_at` null/error |
| Sources | Scryfall metadata; mtgch names + zhs faces (same rules as today) |
| Images | Store URLs only; respect `image_cdn` config + zhs-first art |
| Rate limit | Keep `REQUEST_GAP≈0.12s` for Scryfall |
| Cache | Disk or DB-side “negative cache” for 404s with TTL |
| Failure | Set `card_printings.error`; list still shows set/number |

**Important:** enrichment is **not** on the buyer request path except optional short “wait up to N ms for pending job” — default is non-blocking.

---

## 8. Caching strategy

Phase 1 (ship without Redis):

- Rely on Postgres + short HTTP `Cache-Control: private, max-age=5` for anonymous list GETs **or** no cache until measured.

Phase 2 (if needed):

- Redis keys like `listings:v1:{hash(params)}` TTL 10–30s.  
- Invalidate prefix on any inventory/wants mutation (or TTL-only for simplicity).

At 2000 DAU, Phase 1 is enough if indexes are correct.

---

## 9. Frontend changes

| Area | Change |
|------|--------|
| `loadData()` | Replace Storage/full JSON load with paginated `/api/v1/listings` + `/wants` |
| Filters | Load options from `/meta/filters`; refetch page 1 on change |
| Pagination | Keep `PAGE_SIZE=60`; “load more” → `page++` API |
| Cart | Still localStorage; card ids = inventory UUIDs (stable) |
| Login | Token storage; admin uses same API |
| Admin CRUD | `fetch` to `/me/inventory` instead of supabase-js |
| Remove | Dependency on `publish` Edge Function, Storage snapshot for lists |

Visual product (grid, modal, 无中文印刷图 badge) stays.

---

## 10. Deployment topology

### 10.1 Phase A — single VPS (recommended start)

```
Docker Compose:
  - nginx:443
  - api
  - worker
  - postgres
  - (optional) redis
```

TLS: Caddy or Nginx + Let’s Encrypt.  
Domain: `claystan.cc` A/AAAA → VPS; keep or drop GitHub Pages.

### 10.2 Phase B — split (only if needed)

- Managed Postgres or separate DB host  
- API/worker on app host  
- Object storage only if we later host assets (not images of cards)

### 10.3 Backups

- Nightly `pg_dump` to offsite (R2/S3/B2) + 14–30 day retention  
- Existing logical JSON backup ideas remain useful as secondary  
- Test restore quarterly

### 10.4 Observability

- `/healthz`, structured logs, basic disk/CPU alerts  
- Error rate on enrichment queue

---

## 11. Security

| Topic | Approach |
|-------|----------|
| Auth | HTTP-only secure cookies **or** Bearer access + rotate refresh; short access TTL |
| Authorization | Server-side owner checks on every write (never trust client seller_id) |
| Rate limit | Login + public list endpoints (per IP) |
| Secrets | Env files / Docker secrets; never in git |
| SQL | Parameterized queries only |
| CORS | Only own origins |
| CSP | `img-src` Scryfall + mtgch CDNs; `connect-src` self API |
| Admin invite | Seed first user; invite-only registration (match current model) |

---

## 12. Alternatives considered

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **A. Keep Scheme C** | Cheap, proven, scales reads on CDN | Lag, full rebuild | Stay default until realtime is required |
| **B. Full-table realtime API** | Simple client | Huge payloads, bandwidth, slow | **Reject** |
| **C. Paginated realtime (this doc)** | Fresh data, small payloads, small VPS | More ops than Pages | **Recommend** when leaving Scheme C |
| **D. Supabase Realtime + client SQL** | Less custom API | Exposes schema surface, harder CSP/RLS for public catalog, egress cost | Possible hybrid later; not first choice for public list |
| **E. SSR (Next etc.)** | SEO | Overkill; catalog is app-like | Skip |
| **F. Host images ourselves** | Control | Bandwidth/cost/legal ops | **Reject** |

---

## 13. Migration plan (high level)

| Stage | Work | Exit criteria |
|-------|------|----------------|
| M0 | Design approved; VPS + domain plan | This doc accepted |
| M1 | Schema + API skeleton + health | `/listings` returns empty page |
| M2 | Auth + profile + inventory CRUD | Admin can manage stock on new API |
| M3 | Enrichment worker parity with build_common | New cards get names/images within seconds |
| M4 | Public UI on paginated API | Feature parity for browse/filter/cart |
| M5 | Data migration from Supabase | Row counts match; smoke test |
| M6 | Dual-run / cutover DNS | Scheme C cold standby for 1–2 weeks |
| M7 | Decommission Pages deploy for data path | Docs updated |

Rollback: point DNS back to Pages; Supabase still writable if dual-write not used. Prefer **read cutover only** first (writes still Supabase) only if dual-write is implemented — **default is big-bang write cutover after dry-run import** to avoid dual-write complexity.

---

## 14. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Enrichment backlog after bulk import | Bulk import enqueues unique printings; show placeholder; progress in admin |
| Scryfall rate limits | Disk cache; single worker; backoff |
| No Chinese face for a printing | `image_lang` + badge 无中文印刷图 (already productized) |
| Search quality | Start ILIKE/trigram; revisit FTS |
| Single VPS failure | Nightly backups; document restore; optional cold standby later |
| SEO | Secondary; optional prerender later |

---

## 15. Key Decisions

1. **Paginated SQL reads, not full JSON dumps** — matches UI page size and keeps bandwidth low at 2000 DAU.  
2. **Self-hosted Postgres + thin API** — full control; one VPS enough at target scale.  
3. **Async enrichment table `card_printings`** — buyers never wait on Scryfall; reuse existing enrich rules.  
4. **Images remain external hotlinks** — no self-hosted image bandwidth.  
5. **No publish button for visibility** — DB commit is live; optional re-enrich only.  
6. **Docker Compose single node first** — delay Kubernetes/microservices.  
7. **Auth simplified invite-only JWT** — parity with current product; OIDC later if needed.  
8. **Keep Scheme C as production until M6** — this design is additive; no forced rewrite of the live path before readiness.

---

## 16. Open Questions

1. **API language preference:** Go (static binary, low RAM) vs Python FastAPI (reuse `build_common` more easily)?  
2. **Cutover strategy:** big-bang vs temporary dual-write? (Design default: big-bang after import dry-run.)  
3. **Domain:** keep `claystan.cc` only, or `api.claystan.cc` subdomain?  
4. **Registration:** remain fully invite-only, or allow open signup with moderation?  
5. **Timeline:** when is realtime a hard requirement vs keep optimizing Scheme C?

---

## 17. PR Plan

Incremental PRs against a feature branch / new repo section `server/` (or monorepo `apps/api`). Order is dependency-safe.

### PR1 — Scaffold & health

- **Title:** `chore(server): Docker Compose skeleton (nginx, api, postgres)`  
- **Affects:** `server/docker-compose.yml`, `server/api` hello world, `server/nginx.conf`, `.env.example`  
- **Depends on:** none  
- **Description:** Bring-up local stack; `/api/v1/healthz` only.

### PR2 — Schema & migrations

- **Title:** `feat(server): Postgres schema for profiles, inventory, wants, card_printings`  
- **Affects:** SQL migrations, migration runner  
- **Depends on:** PR1  
- **Description:** Tables + indexes matching uniqueness rules; seed script.

### PR3 — Auth & profiles API

- **Title:** `feat(server): invite-only login and profile CRUD`  
- **Affects:** auth handlers, JWT/cookies, `/me` routes  
- **Depends on:** PR2  
- **Description:** Password login; profile completeness rules.

### PR4 — Inventory & wants CRUD + batch

- **Title:** `feat(server): owner inventory/wants CRUD and batch upsert`  
- **Affects:** API routes, validation mirroring admin forms  
- **Depends on:** PR3  
- **Description:** Feature parity with admin write path; enqueue enrichment stubs.

### PR5 — Enrichment worker

- **Title:** `feat(server): Scryfall/mtgch enrichment worker for card_printings`  
- **Affects:** worker package; port rules from `build_common.py`  
- **Depends on:** PR2 (optionally PR4 for triggers)  
- **Description:** Async fill names/images; disk cache; zhs art rules.

### PR6 — Public paginated list APIs

- **Title:** `feat(server): GET /listings and /wants with filters`  
- **Affects:** list queries, `/meta/filters`  
- **Depends on:** PR2, PR5 (can mock printings first)  
- **Description:** Page size 60; response shape compatible with frontend card model.

### PR7 — Frontend public site on API

- **Title:** `feat(web): load main grid from paginated API`  
- **Affects:** `assets/app.js`, `mtg-ui.js` pagination, CSP/connect-src  
- **Depends on:** PR6  
- **Description:** Remove Storage full-fetch for primary path; keep graceful empty states.

### PR8 — Frontend admin on API

- **Title:** `feat(admin): replace supabase-js CRUD with API client`  
- **Affects:** `admin/admin.js`, remove publish-to-GitHub path  
- **Depends on:** PR3–PR5  
- **Description:** Login + CRUD + batch import; live list without snapshot wait.

### PR9 — Migration tooling

- **Title:** `feat(server): import from Supabase logical backup`  
- **Affects:** import script from `backup_supabase.py` archives  
- **Depends on:** PR2–PR5  
- **Description:** One-shot migration + enrich backfill.

### PR10 — Production cutover & docs

- **Title:** `docs/ops: cutover runbook, backups, decommission Scheme C data path`  
- **Affects:** README, CLAUDE, deploy scripts, `pg_dump` cron  
- **Depends on:** PR7–PR9 validated in staging  
- **Description:** DNS, TLS, backup restore drill; freeze old publish workflow.

---

## 18. Success metrics

| Metric | Target |
|--------|--------|
| List API p95 latency | &lt; 200 ms on VPS (cached warm) |
| Time from admin save to visible on main list | &lt; 2 s (enrichment may lag images) |
| Image time-to-display for known printing | &lt; 1 s if already in `card_printings` |
| Host bandwidth (app only) | comfortably under 5 Mbps avg at 2000 DAU |
| Backup restore drill | successful within 1 hour RTO for DB |

---

## Document history

| Date | Change |
|------|--------|
| 2026-07-17 | Initial design from recommended self-hosted paginated realtime architecture |
