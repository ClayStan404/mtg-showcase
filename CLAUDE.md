# CLAUDE.md

> See `QWEN.md` for the full reference. This file is a concise guide for quick orientation.
>
> **Future architecture (not implemented):** `docs/SELF_HOSTED_REALTIME_DESIGN.md` — self-hosted paginated realtime reads.

## What this project is

Static **MTG buylist + sell list** website (GitHub Pages shell + Supabase Storage data snapshots, `claystan.cc`). Sellers/buyers manage data in an **admin SPA** (`/admin/`) backed by **Supabase** (Tokyo). Visitors search/filter/wishlist, then contact sellers off-site. No in-site checkout or payment.

`master` holds source only; **generated artifacts are never committed**.

**Scheme C (near-live lists, not DB-direct reads):** admin save → ~45s debounced auto-sync (or **立即同步**) → Edge Function `publish` → `workflow_dispatch` `mode=data` → export → enrich → **`upload_site_data.py`** → public Storage bucket `site-data` (`cards.json` / `wants.json`). Main site **fetches Storage first** (fallback: inlined `cards-data.js` / `data/*.json`). Full Pages deploy only on `push master` or `mode=full`.

## Data flow

```
sellers/buyers (write)  admin SPA ──> Supabase (profiles + inventory + wants)
                                     │   ~45s debounce / 「立即同步」 / hourly cron
                                     │   (publish EF → workflow_dispatch mode=data)
                                     ▼
                  export_*_to_txt.py  → inventory|wants/{uid}.txt
                                     ▼
                  build_data.py / build_wants.py  → data/*.json + assets/*-data.js
                    (Scryfall metadata + mtgch names/zhs art; image_cdn hotlinks)
                                     ▼
                  upload_site_data.py → Storage site-data/{cards,wants}.json  ← buyers read
                                     │
                  push / mode=full: assemble site/ → deploy-pages (HTML/CSS/JS shell)
```

Shared code: `build_common.py` (ScryfallClient, image CDN resolve, payload/cache tools), `export_common.py`, `inventory_format.py` (line parsers + field conventions).

Frontend: Storage snapshot preferred; inline JS is resilience fallback. Shared UI in `assets/mtg-ui.js`; shell `assets/app.js`; admin overrides `cardHtml` + CRUD/batch/import/sync. Supabase: vendored `assets/vendor/supabase-js.min.js` + `assets/supabase-client.js` (`dataBaseUrl()`, lazy load on main site).

## Key constraints

- **Artifacts not in git**: `inventory/*.txt`, `wants/*.txt`, `data/cards.json`, `data/wants.json`, `assets/*-data.js` (generated at deploy). Optional personal log: root `claystan.txt` (seller notes; not required at runtime).
- **Field format**:

| Field | Input | Internal |
|-------|-------|----------|
| Language | `e`/`z`/`j`/`o` (empty=`e`) | `en` / `zhs` / `ja` / `other` |
| Foil | empty/`0`=no, `1`=yes | bool |
| Quantity | empty=1 | int ≥ 1 |
| Price | empty/`0`=market, `>0`=fixed | numeric(10,2) |
| Must (wants) | empty/`0`=any, `1`=exact | bool |

- **txt line**: `set number lang foil [qty] [price] [# note]` (inventory) / `… [must] [price] [# note]` (wants). Middle fields not skippable.
- `o` (other) displays as 其他; Scryfall image fetch uses `en`.
- `seller`/`buyer`, `city`, `contact` required (from `profiles`; export writes `# seller:` / `# buyer:` headers).
- Sold out = **delete row**, not qty `0`.
- **price display**: `price=0` no flag; `price>0` shows `¥X.XX`.
- **CART_KEY** = `mtg-wishlist-v2` (ids include price + note_hash).
- CSP: main `script-src 'self'`, `img-src` includes `cards.scryfall.io` + `images.mtgch.com`, `connect-src` Supabase; admin also `mtgch.com` + Scryfall API. Pagination `PAGE_SIZE=60`. Images: `normal` min, modal `large` — never prefer `small` for bandwidth.
- UI: header **brand left / account actions top-right** (`.header-top`); mobile touch targets + safe-area.

## Image CDN & Chinese art

- **`site_config.json` → `image_cdn`**: `"scryfall"` (production) or `"mtgch"`. Snapshots store **hotlink URLs only** (visitors do not hit card APIs).
- Build metadata: primarily **Scryfall**; Chinese names + optional zhs faces from **mtgch**.
- Admin live enrich (preview/new cards): **mtgch first**, Scryfall fallback.
- `lang=zhs`: prefer Chinese face art (`zhs_image_uris` / true Scryfall zhs printing) over English; inventory language wins over CDN host flip.
- Sticky fields (avoid re-resolve every incremental build):
  - `image_cdn_attempted` — preferred host last tried
  - `zhs_art_attempted` — Chinese face already attempted
  - `image_lang` — face language of chosen art (from resolve path, not URL guessing)
- Sticky cost: if preferred CDN later gains art, no auto switch until config flip or markers cleared.
- UI badge **无中文印刷图** when `lang=zhs` but `image_lang` is not Chinese (e.g. `msc 211` — no zhs face in data sources).

## Common commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

gh workflow run auto-update.yml --repo ClayStan404/mtg-showcase -f mode=data
gh workflow run auto-update.yml --repo ClayStan404/mtg-showcase -f mode=full

SUPABASE_SERVICE_ROLE_KEY=<key> python3 scripts/export_inventory_to_txt.py
SUPABASE_SERVICE_ROLE_KEY=<key> python3 scripts/export_wants_to_txt.py
python3 scripts/build_data.py --validate-only
python3 scripts/build_data.py --no-cache
SUPABASE_SERVICE_ROLE_KEY=<key> python3 scripts/upload_site_data.py

# Logical DB backup (daily: workflow db-backup.yml on self-hosted)
SUPABASE_SERVICE_ROLE_KEY=<key> python3 scripts/backup_supabase.py
SUPABASE_SERVICE_ROLE_KEY=<key> python3 scripts/backup_supabase.py --no-upload
SUPABASE_SERVICE_ROLE_KEY=<key> python3 scripts/restore_supabase_backup.py backups/supabase-XXXX.tar.gz --dry-run

pip install -r requirements-dev.txt
python3 -m pytest tests/ -q
ruff check scripts/ tests/
```

## External dependencies

- **Supabase** (Tokyo): project `rkvtizboyikrjowfogoc`. Tables `profiles` / `inventory` / `wants` + RLS. Secrets: `SUPABASE_SERVICE_ROLE_KEY` (Actions + local export/upload/backup). Public anon key in `site_config.json`. Edge Function `publish` (`verify_jwt=true`) → GitHub `workflow_dispatch` with `{mode}`. Storage: `site-data` (public list snapshots); `db-backups` (private logical archives, service_role only). Free plan has **no** platform daily DB backups — use `scripts/backup_supabase.py` / `db-backup.yml` or upgrade to Pro.
- **Scryfall**: `https://api.scryfall.com/cards/{set}/{number}/{lang}` — rate limit `REQUEST_GAP=0.12s`, disk cache `.cache/scryfall/`, TTL 30d, 404 `.notfound` sentinel, 429 `Retry-After`. CDN `cards.scryfall.io`.
- **mtgch**: `https://mtgch.com/api/v1/card/{set}/{number}/` — zh names + optional `zhs_image_uris` / `images.mtgch.com`. Disk-cached. Docs: https://mtgch.com/api/v1/docs

## Git / deploy notes

- Triggers: `push master` (full) / hourly runner cron (`mode=data` default) / admin sync / manual `workflow_dispatch`.
- `paths-ignore` skips pure docs on some setups; code + `site_config` changes deploy.
- Checkout `clean: false` keeps `.cache/scryfall` + previous `data/*.json`.
- Heartbeat: `heartbeat.yml` **hourly** schedule only (GitHub-hosted; no `workflow_run`); opens issue if no success for >2h; recovery close may lag up to ~1h. ~720 min/mo hosted, under free private 2000.
- Hermes bots (private `config_rc`): deploy alerts + card query + broadcasts.
- Cache bust `?v=` via `bump_all_caches` in deploy artifact only.
- `.gitignore`: `site/`, `inventory/`, `wants/`, `backups/`, `data/cards.json`, `data/wants.json`, `assets/*-data.js`, `.cache/`, `.venv/`, etc.
- Daily backup: `db-backup.yml` (self-hosted) → local `backups/` + private Storage `db-backups/`.
- Commit/PR messages in English. Do not commit/push unless the user asks.
