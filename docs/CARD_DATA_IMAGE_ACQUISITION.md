# Card Data & Image Acquisition — Implementation Report

How the site reliably obtains Chinese/English card **metadata** and **card art** at build time, deploy time, and in the admin live-preview path. Covers the two data sources, their division of labor, caching/sticky strategy, language precedence, and the frontend fallback chain.

## 1. Two Data Sources

| Source | API | Responsibility | CDN host |
|--------|-----|----------------|---------|
| **Scryfall** | `api.scryfall.com/cards/{set}/{number}/{lang}` | Authoritative **metadata** for English/Japanese cards: name, `type_line`, `mana_cost`, `cmc`, Oracle/printed text, images | `cards.scryfall.io` |
| **mtgch** | `mtgch.com/api/v1/card/{set}/{number}/` | **Chinese names** (`zhs_name`) + optional **Chinese face art** (`zhs_image_uris`) | `images.mtgch.com` |

Build time: Scryfall is primary, mtgch fills Chinese. Admin live preview: mtgch first, Scryfall fallback — the order is intentionally reversed (see §9).

## 2. Language Mapping (`scripts/inventory_format.py:13-50`)

Input tokens `e/z/j/o` → internal `en/zhs/ja/other`. The critical helper is `scryfall_lang()`:

- `other → en` (other-language stock falls back to English printing for image fetch)
- `zhs → zhs`

`LANG_LABEL` maps internal codes back to display labels (英文 / 简中 / 日文 / 其他).

## 3. Build-Time: Scryfall Metadata Fetch (`build_common.py:250-309`)

`ScryfallClient.fetch_card()` is hardened against partial failures:

1. **Dual-URL fallback** — for non-en lang, first request `/{set}/{number}/{lang}`; on 404 retry `/{set}/{number}` (e.g. a ja card with no Japanese printing → English card returned). This is how non-zhs languages degrade gracefully.
2. **Three-layer disk cache** (`.cache/scryfall/`, TTL 30 days):
   - Positive cache: `{set}_{num}_{api_lang}.json`
   - Negative sentinel: `{set}_{num}_{api_lang}.notfound` — a 404 writes an empty file so subsequent builds return `None` within TTL without re-hitting the API. Prevents wrong set/number from re-firing 404s every run.
   - Expired-cache fallback: on 5xx/timeout when the fresh fetch fails, fall back to the stale cached JSON (logged `⚠ 回退到过期缓存`).
3. **Key/content consistency** — only cache to the `api_lang` path when `data.lang == api_lang` (`build_common.py:307`). In a fallback scenario (ja 404 → en card) the data lang mismatches the path; caching it would put English data under the ja key and block auto-refresh once Scryfall later adds the Japanese printing.
4. **Rate limiting** — `REQUEST_GAP=0.12s` (Scryfall recommends 0.1s + margin). HTTP 429 honors the `Retry-After` header. Transient 5xx retries twice with exponential backoff; permanent 4xx (400/401/403/404/405/410) raises immediately.

## 4. Build-Time: Chinese Name Acquisition (`build_common.py:686-752, 816-866`)

**Every language needs a Chinese name**, not just `zhs` stock — an English listing still gets one (e.g. `one/370 en → 暗峰山崖`), because the main-site `displayName` prefers `name_zh`.

- `fetch_zh_name()` → `fetch_mtgch_card()`, reading `zhs_name` → `atomic_official_name` → `atomic_translated_name`.
- **CJK gate** `looks_like_chinese_name()` (`build_common.py:641-655`): the value must contain a CJK ideograph (U+4E00–9FFF + Ext A U+3400–4DBF). Latin-only mtgch fallbacks are rejected so an English name never lands in `name_zh` and confuses `displayName`.
- **Sticky `zh_name_attempted` + `zh_name_attempted_at`** — while TTL-fresh, mtgch is not re-queried even if still no CJK name (`ensure_zh_name`). Expired / legacy (bool only) rows get a repair pass; `--repair-sticky` clears markers.
- **zhs stock**: `printed_name` first; if non-CJK, query mtgch; if still none, fall back to `name_en`. Also repairs `name_printed` when it was missing/non-CJK.

## 5. Build-Time: Image Resolution — Core Precedence (`build_common.py:392-492`)

`resolve_images()` returns `(image_dict, art_lang)`. **`art_lang` is set from the resolution path, not inferred from URL shape** — Scryfall URLs do not encode language in the path (different face UUIDs), so `is_mtgch_zhs_url()` only detects mtgch Chinese paths (`/zhs/`), never Scryfall Chinese art.

### `lang=zhs` (Chinese stock) — inventory language wins over CDN host preference

```
1. mtgch zhs_image_uris (strict Chinese face)         -> art_lang="zhs"
2. Scryfall Chinese printing (only if card.lang is zhs/zh) -> art_lang="zhs"
3. Neither available -> English art via preferred_cdn_chain(pick_lang="en") -> art_lang="en"
```

Example: `pip/717` has no Scryfall zhs printing (404) but mtgch has `zhs_image_uris` — Chinese stock must use those, not the English Chaos Warp art.

### Non-zhs — preferred CDN first, other CDN fallback

`site_config.image_cdn` is tried first; on miss the other CDN is tried (`build_common.py` preferred_cdn_chain). **Code fallback when config omits the key:** `mtgch`. **Production `site_config.json`:** `"scryfall"`. The preferred host is sticky for non-zhs rows (with TTL — see §6).

### `pick_images()` (`build_common.py:528-561`)

Extracts small/normal/large from Scryfall- or mtgch-shaped JSON: when `lang=zhs`, prefer `zhs_image_uris` → `image_uris` → first `card_faces`/`faces` with art → mtgch `image_url` single-URL mode (all three sizes identical, modal "large" same quality as grid).

## 6. Incremental Build & Sticky Markers (`build_common.py:755-813`)

`load_previous_enrichment()` reuses old `cards.json` metadata keyed by `set|number|lang` to speed up rebuilds. Three sticky markers avoid repeated network calls:

| Marker | Purpose |
|--------|---------|
| `image_cdn_attempted` (+ `_at`) | For non-zhs: if preferred CDN host unchanged and attempt is fresh (TTL = 30d), skip re-resolve |
| `zhs_art_attempted` | Diagnostic — zhs with Chinese face art is not re-resolved even on CDN flip |
| `zh_name_attempted` (+ `_at`) | Chinese name queried once; while TTL-fresh, never re-queried even if still empty |

Legacy rows with `*_attempted=True` but no `*_at` timestamp are treated as **expired** once (one repair pass), then stick with a new timestamp. Manual force: `build_data.py` / `build_wants.py --repair-sticky`. Builds log a count of sticky-empty `name_zh` rows.

`ensure_image_cdn` key rules:

- **zhs already on Chinese face art** → CDN flip does NOT re-resolve (language/face wins over CDN preference).
- **zhs still on English (or empty) art** → re-resolve every build (mtgch may have `zhs_image_uris` while Scryfall lacks a zhs printing, e.g. `pip/671`). Disk cache keeps this cheap; a re-resolve TTL could be added if zhs-English volume ever slows builds.

## 7. Frontend: Data Loading Priority (`assets/app.js` `loadCatalog`)

Scheme C main path is the Storage snapshot. Pages `data/*.json` and inlined `cards-data.js` are last-resort shells (updated only on `mode=full` / push), not a timeout fallback.

1. **Storage** `{data_base_url}/cards.json` with `cache: "reload"` + 8s timeout (one retry on abort/timeout). Timeout **throws** — do not serve a stale Pages/inline catalog.
2. **Pages/local** `data/cards.json` — only if Storage is unset, 4xx/5xx, or the payload is invalid.
3. **Inlined** `window.__MTG_DATA__` / `__MTG_WANTS__` if `data/` also fails.

`dataBaseUrl()` (`supabase-client.js`) derives from build-time `site.data_base_url` or `supabase_url + bucket`. Storage objects use `Cache-Control: public, max-age=30, must-revalidate`.

## 8. Frontend: Card Art Rendering (`assets/mtg-ui.js:405-425`)

- `cardImageSrc()`: `image.normal` first (488×680, crisp on retina), fallback `image.small`, then a 1×1 transparent placeholder (avoids `src=""` triggering a request to the current page URL).
- Images are **hotlinked** (`cards.scryfall.io` / `images.mtgch.com`) — visitors **never hit card APIs**.
- `displayName()` (`mtg-ui.js:215-220`): if `name_zh` differs from `name_en`, use `name_zh`; else `name_printed || name_zh || name_en`.
- **"无中文印刷图" badge** (`mtg-ui.js:421-425`): when `lang==="zhs"` but `image_lang` is not `zhs`/`zh`, a `无中文印刷图` flag is shown (e.g. `msc 211` has no Chinese face in any source, so English art is shown with a notice).

## 9. Admin Live Enrichment (`admin/admin.js` `ensureDisplayEnrichment` / `fetchScryfallJson`)

Preview path for newly added cards not yet in the Storage snapshot — **order reversed vs build time**:

- `ensureDisplayEnrichment()`: **mtgch first** (CN-friendly: one call yields both Chinese name and CN-CDN image), fall back to Scryfall only if image or name is still missing.
- `fetchScryfallJson()` dual-host fallback: `api.scryfall.com` + `api.scryfall.io`; for non-en, dual path (`/{lang}` + no-lang).
- `mergeKeepExisting()`: override only with non-empty values; never clobber existing fields with `""`/`null`. For `image`, requires a usable URL.
- `_enrichInflight` Map dedupes concurrent requests for the same key (prefetch + decorate coalesce).
- `pickImageBundle` / `pickNames` mirror the build-side `pick_images` / `fetch_zh_name` logic.

## 10. Key Design Principles

1. **Snapshots store hotlink URLs only** — visitors make zero card-API calls; the browser hits the CDN directly.
2. **`art_lang` set by resolution path** — never guessed from URL shape, because Scryfall URLs do not encode language.
3. **Inventory language > CDN preference** — zhs stock strictly prefers Chinese face art (mtgch `zhs_image_uris` → Scryfall zhs printing → English fallback + badge).
4. **CJK gate** — rejects Latin-only Chinese-name candidates, keeping `displayName` from mistaking English for Chinese.
5. **Three sticky markers** — incremental builds re-resolve only rows whose state is wrong; typical inventory sizes issue very few network requests.
6. **Build: Scryfall primary; admin: mtgch primary** — build wants authoritative metadata; admin preview wants CN reachability and a Chinese name in one round-trip.
7. **Negative cache + stale-cache fallback** — 404s are not re-fired, 5xx falls back to expired data, keeping builds robust.

## 11. Field Format Reference

| Field | Input | Internal |
|-------|-------|----------|
| Language | `e`/`z`/`j`/`o` (empty=`e`) | `en` / `zhs` / `ja` / `other` |
| Foil | empty/`0`=no, `1`=yes | bool |
| Quantity | empty=1 | int ≥ 1 |
| Price | empty/`0`=market, `>0`=fixed | numeric(10,2) |
| Must (wants) | empty/`0`=any, `1`=exact | bool |

txt line (inventory): `set number lang foil [qty] [price] [# note]`
txt line (wants): `set number lang foil [qty] [must] [price] [# note]`

Middle fields are not skippable. `o` (other) displays as 其他; Scryfall image fetch uses `en`.

## 12. Quick Reference — Build Data Fields Per Card

Built by `base_from_card()` (`build_common.py:686-752`) and persisted into `cards.json` / `wants.json`:

| Field | Source | Notes |
|-------|--------|-------|
| `name_en` | Scryfall `name` | English card name |
| `name_zh` | mtgch `zhs_name` (CJK-gated) | Empty if no CJK candidate; sticky via `zh_name_attempted` |
| `name_printed` | Scryfall `printed_name` | For zhs: repaired to CJK name if missing |
| `type_line` / `type_line_en` | Scryfall | English type line for filtering |
| `types` | derived from `type_line_en` | Tags: creature/instant/… |
| `mana_cost` / `cmc` | Scryfall | Double-faced joined with `//` |
| `text` | Scryfall `printed_text`/`oracle_text` | Faces joined with `\n//\n` |
| `image` | `resolve_images()` | `{small, normal, large}` hotlink URLs |
| `image_lang` | resolution path | Face language of chosen art (`zhs`/`en`/…) |
| `image_cdn_attempted` | preferred CDN | Sticky host marker |
| `zhs_art_attempted` | diagnostic | True after a zhs resolve |
| `zh_name_attempted` | sticky | True after mtgch name query |

## 13. Related Files

- `scripts/build_common.py` — `ScryfallClient`, `resolve_images`, `pick_images`, `ensure_image_cdn`, `ensure_zh_name`, `looks_like_chinese_name`
- `scripts/build_data.py` — inventory → `cards.json` enrichment loop
- `scripts/build_wants.py` — wants → `wants.json` (same enrichment core)
- `scripts/inventory_format.py` — `scryfall_lang`, `LANG_INPUT_MAP`, field parsers
- `assets/app.js` — `loadCatalog` / `loadData` Storage-first fallback chain
- `assets/mtg-ui.js` — `cardHtml`, `cardImageSrc`, `displayName`, "无中文印刷图" badge
- `assets/supabase-client.js` — `dataBaseUrl()` derivation
- `admin/admin.js` — `ensureDisplayEnrichment`, `fetchMtgchJson`, `fetchScryfallJson`, `pickImageBundle`
- `site_config.json` — `image_cdn` (`scryfall` | `mtgch`), `data_base_url`, `supabase_url`
