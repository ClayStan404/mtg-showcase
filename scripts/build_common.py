#!/usr/bin/env python3
"""build_data / build_wants 共享的构建逻辑：Scryfall 富化、缓存、payload 工具。

提取自 build_data.py，供两个 build 脚本复用，避免 build_wants 反向依赖 build_data。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inventory_format import scryfall_lang  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / ".cache" / "scryfall"
SITE_CONFIG = ROOT / "site_config.json"

# Scryfall 建议最小 0.1s/请求；0.12 含安全余量
REQUEST_GAP = 0.12
# Scryfall/mtgch 磁盘缓存 TTL（秒），超期则重拉，让 Oracle 文本/规则面更新后自动刷新
CACHE_TTL = 30 * 24 * 3600
USER_AGENT = "MTGShowcase/1.0 (personal inventory; github pages)"


def bump_cache_buster(html_path: Path, asset_filename: str, content: bytes) -> None:
    """用内容 md5 前 8 位更新 html 里 <asset_filename>?v=... 的版本号。

    正则 path-agnostic（匹配 `assets/x.js?v=`、`/admin/admin.js?v=`、
    `/assets/vendor/y.min.js?v=` 等），所以同一文件名在 root index.html 和
    admin/index.html 都能 bump。cards-data.js / wants-data.js 内容变化即自动
    击穿浏览器缓存，无需手动改 ?v=N。app.js / style.css 等也统一 bump。
    """
    if not html_path.exists():
        return
    digest = hashlib.md5(content).hexdigest()[:8]
    text = html_path.read_text(encoding="utf-8")
    pattern = re.compile(rf"({re.escape(asset_filename)}\?v=)[^\"'\s]+")
    new_text, n = pattern.subn(rf"\g<1>{digest}", text)
    if n and new_text != text:
        html_path.write_text(new_text, encoding="utf-8")


# root index.html + admin/index.html 共享引用的静态资源（?v= 需在两处同步 bump，
# 否则 admin 页用旧缓存——review 指出 admin/index.html 的 ?v=0 不在原 bump 范围内）
_STATIC_CACHE_ASSETS = [
    ("app.js", "assets/app.js"),
    ("style.css", "assets/style.css"),
    ("mtg-ui.js", "assets/mtg-ui.js"),
    ("supabase-client.js", "assets/supabase-client.js"),
    ("supabase-js.min.js", "assets/vendor/supabase-js.min.js"),
    ("admin.js", "admin/admin.js"),
    ("admin.css", "admin/admin.css"),
]
_HTML_CACHE_TARGETS = [ROOT / "index.html", ROOT / "admin" / "index.html"]


def bump_all_caches(data_filename: str, data_content: bytes) -> None:
    """Bump ?v= for all shared static assets + the data file (cards-data.js /
    wants-data.js) in BOTH index.html and admin/index.html. Content-hash based：
    未改动的 asset 保持原 ?v=（不无谓击穿），改动的换新 hash。"""
    for name, rel in _STATIC_CACHE_ASSETS:
        path = ROOT / rel
        if path.exists():
            content = path.read_bytes()
            for html in _HTML_CACHE_TARGETS:
                bump_cache_buster(html, name, content)
    for html in _HTML_CACHE_TARGETS:
        bump_cache_buster(html, data_filename, data_content)


def stable_payload_bytes(payload: dict[str, Any], var_name: str) -> bytes:
    """生成剔除 generated_at 的 JS payload 字节，供 bump_cache_buster 用稳定内容算 ?v=。

    写入文件的 JS 仍含 generated_at（前端用它显示“最后更新”），但 cache buster 基于
    剔除时间戳的内容计算，避免每小时时间戳变化导致 ?v= 抖动、浏览器无意义重下。
    """
    stable = {k: v for k, v in payload.items() if k != "generated_at"}
    return f"{var_name}={json.dumps(stable, ensure_ascii=False, separators=(',', ':'))};\n".encode()


def payload_unchanged(output_path: Path, new_payload: dict[str, Any]) -> bool:
    """比较新 payload 与已存在的 output（忽略 generated_at 时间戳）。

    generated_at 每小时部署都会变，但数据未必变化；忽略它比较可避免无意义写入，
    也让 bump_cache_buster 的 ?v= 不随时间戳抖动。前端仍用 generated_at 显示
    “最后更新”时间——数据未变时旧时间戳对用户同样有效，故可安全忽略。
    """
    if not output_path.exists():
        return False
    try:
        old = json.loads(output_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(old, dict):
        return False
    old_wo_ts = {k: v for k, v in old.items() if k != "generated_at"}
    new_wo_ts = {k: v for k, v in new_payload.items() if k != "generated_at"}
    return old_wo_ts == new_wo_ts


def data_base_url_from_supabase(supabase_url: str, bucket: str = "site-data") -> str:
    """Public Storage URL prefix for scheme-C snapshots (cards.json / wants.json)."""
    base = (supabase_url or "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/storage/v1/object/public/{bucket}"


def load_site_config() -> dict[str, Any]:
    if SITE_CONFIG.exists():
        try:
            cfg = json.loads(SITE_CONFIG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            # site_config.json 损坏时回退默认配置，避免直接崩掉整轮 build
            print(f"⚠ site_config.json 解析失败，使用默认配置: {e}", file=sys.stderr)
            cfg = {
                "title": "万智牌 Sales List",
                "subtitle": "实体卡展示 · 站外联系成交",
            }
    else:
        cfg = {
            "title": "万智牌 Sales List",
            "subtitle": "实体卡展示 · 站外联系成交",
        }
    # Scheme C: always expose public snapshot base URL for the frontend.
    # Explicit data_base_url in site_config wins; otherwise derive from supabase_url.
    if not (cfg.get("data_base_url") or "").strip():
        derived = data_base_url_from_supabase(
            str(cfg.get("supabase_url") or ""),
            str(cfg.get("data_bucket") or "site-data"),
        )
        if derived:
            cfg["data_base_url"] = derived
    # Image CDN preference for built snapshots (mtgch | scryfall). Easy rollback.
    cfg["image_cdn"] = normalize_image_cdn(str(cfg.get("image_cdn") or ""))
    return cfg


# Preferred image host written into cards.json / wants.json.
# "mtgch" = images.mtgch.com (better for CN); "scryfall" = cards.scryfall.io.
IMAGE_CDN_MTGCH = "mtgch"
IMAGE_CDN_SCRYFALL = "scryfall"
DEFAULT_IMAGE_CDN = IMAGE_CDN_MTGCH


def normalize_image_cdn(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in (IMAGE_CDN_SCRYFALL, "sf", "scry", "scryfall.com", "cards.scryfall.io"):
        return IMAGE_CDN_SCRYFALL
    return IMAGE_CDN_MTGCH


def image_cdn_preference(cfg: dict[str, Any] | None = None) -> str:
    if cfg is None:
        cfg = load_site_config()
    return normalize_image_cdn(str(cfg.get("image_cdn") or DEFAULT_IMAGE_CDN))


def image_url_matches_cdn(url: str, preferred: str) -> bool:
    u = (url or "").lower()
    if not u:
        return False
    if preferred == IMAGE_CDN_MTGCH:
        return "mtgch.com" in u
    return "scryfall" in u


def image_dict_matches_cdn(image: dict[str, Any] | None, preferred: str) -> bool:
    if not image:
        return False
    return image_url_matches_cdn(
        str(image.get("normal") or image.get("small") or ""), preferred
    )


def is_mtgch_zhs_url(url: str) -> bool:
    """True only for mtgch Chinese CDN paths (.../zhs/...).

    Scryfall URLs never encode language in the path (different face UUIDs),
    so do not use this to detect Scryfall Chinese art — use image_lang.
    """
    return "/zhs/" in (url or "").lower()


class ScryfallClient:
    def __init__(self, use_disk_cache: bool = True) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._last = 0.0
        self.use_disk_cache = use_disk_cache
        if use_disk_cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < REQUEST_GAP:
            time.sleep(REQUEST_GAP - elapsed)
        self._last = time.monotonic()

    def get(self, url: str, *, throttle: bool = True, **kwargs: Any) -> requests.Response:
        for attempt in range(3):
            if throttle:
                self._throttle()
            try:
                resp = self.session.get(url, timeout=30, **kwargs)
                resp.raise_for_status()
                return resp
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                print(f"  ⚠ 网络错误，{wait}s 后重试: {e}", file=sys.stderr)
                time.sleep(wait)
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                if status in (400, 401, 403, 404, 405, 410) or attempt == 2:
                    raise
                # 429 限流：优先遵守 Retry-After 头，避免被封 IP
                wait = 2 ** attempt
                if status == 429 and e.response is not None:
                    ra = e.response.headers.get("Retry-After")
                    if ra:
                        try:
                            wait = max(wait, float(ra))
                        except ValueError:
                            pass
                print(f"  ⚠ HTTP {status}，{wait}s 后重试", file=sys.stderr)
                time.sleep(wait)
        raise RuntimeError("unreachable")  # 逻辑不可达：循环内必然 return 或 raise

    def _cache_path(self, set_code: str, number: str, lang: str) -> Path:
        safe_set = re.sub(r"[^\w.-]", "_", set_code)
        safe_num = re.sub(r"[^\w.-]", "_", number)
        return CACHE_DIR / f"{safe_set}_{safe_num}_{lang}.json"

    def _neg_path(self, set_code: str, number: str, lang: str) -> Path:
        """404 负结果哨兵路径（与正缓存同目录、同命名规则，后缀 .notfound）。"""
        safe_set = re.sub(r"[^\w.-]", "_", set_code)
        safe_num = re.sub(r"[^\w.-]", "_", number)
        return CACHE_DIR / f"{safe_set}_{safe_num}_{lang}.notfound"

    def fetch_card(self, set_code: str, number: str, lang: str) -> dict[str, Any] | None:
        api_lang = scryfall_lang(lang)
        cache_path = self._cache_path(set_code, number, api_lang)
        neg_path = self._neg_path(set_code, number, api_lang)
        # 负结果哨兵：错误 set/number 在 TTL 内直接返回 None，避免每轮重发 404（对齐 fetch_zh_name）
        if self.use_disk_cache and neg_path.exists():
            if time.time() - neg_path.stat().st_mtime < CACHE_TTL:
                return None
        if self.use_disk_cache and cache_path.exists():
            # TTL：超期则忽略缓存重拉，让 Scryfall 数据更新（Oracle 文本/规则面）后刷新
            if time.time() - cache_path.stat().st_mtime < CACHE_TTL:
                try:
                    return json.loads(cache_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass

        urls = [f"https://api.scryfall.com/cards/{set_code}/{number}/{api_lang}"]
        if api_lang != "en":
            urls.append(f"https://api.scryfall.com/cards/{set_code}/{number}")

        data = None
        api_failed = False
        for url in urls:
            try:
                data = self.get(url).json()
                break
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    continue
                if e.response is not None and e.response.status_code in (500, 502, 503, 504):
                    api_failed = True
                    continue
                print(f"  ⚠ 无法获取 {set_code} {number} {lang}: {e}", file=sys.stderr)
                api_failed = True
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                print(f"  ⚠ 网络错误获取 {set_code} {number} {lang}: {e}", file=sys.stderr)
                api_failed = True
                break

        if data is None and api_failed and self.use_disk_cache and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                print(f"  ⚠ 回退到过期缓存: {set_code} {number} {lang}", file=sys.stderr)
                return cached
            except json.JSONDecodeError:
                pass

        # 404（两 url 均未找到且非网络故障）写负哨兵：TTL 内下次直接返回 None，
        # 避免错误 set/number 每轮重发请求。api_failed（5xx/超时）不写，留待重试。
        if data is None and not api_failed and self.use_disk_cache:
            neg_path.write_text("", encoding="utf-8")

        # 仅当返回数据的 lang 与请求 lang 一致时才缓存到 api_lang 路径。
        # 回退场景（如 ja 卡无日文印刷 -> 404 -> 取 en）下 data.lang != api_lang，
        # 不缓存，避免把英文数据写入 ja 缓存路径造成键与内容不符、且 Scryfall
        # 日后新增该印刷后无法自动刷新。
        if data is not None and self.use_disk_cache and data.get("lang") == api_lang:
            cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    @staticmethod
    def _mtgch_safe_names(set_code: str, number: str) -> tuple[str, str]:
        safe_set = re.sub(r"[^\w.-]", "_", set_code)
        safe_num = re.sub(r"[^\w.-]", "_", number)
        return safe_set, safe_num

    def _mtgch_cache_path(self, set_code: str, number: str) -> Path:
        safe_set, safe_num = self._mtgch_safe_names(set_code, number)
        return CACHE_DIR / f"mtgch_{safe_set}_{safe_num}.json"

    def _mtgch_neg_path(self, set_code: str, number: str) -> Path:
        safe_set, safe_num = self._mtgch_safe_names(set_code, number)
        return CACHE_DIR / f"mtgch_{safe_set}_{safe_num}.notfound"

    def fetch_mtgch_card(self, set_code: str, number: str) -> dict[str, Any] | None:
        """Full card JSON from mtgch (shared by zh name + image CDN preference).

        Caches positive JSON and 404 negative sentinel under .cache/scryfall/.
        """
        cache_path = self._mtgch_cache_path(set_code, number)
        neg_path = self._mtgch_neg_path(set_code, number)
        if self.use_disk_cache and neg_path.exists():
            if time.time() - neg_path.stat().st_mtime < CACHE_TTL:
                return None
        if self.use_disk_cache and cache_path.exists():
            if time.time() - cache_path.stat().st_mtime < CACHE_TTL:
                try:
                    return json.loads(cache_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass

        url = f"https://mtgch.com/api/v1/card/{set_code}/{number}/"
        try:
            # throttle=False: mtgch is separate from Scryfall rate limit; zh+image share cache.
            data = self.get(url, throttle=False).json()
            if not isinstance(data, dict):
                return None
            if self.use_disk_cache:
                cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                # Keep legacy zhname_*.txt for tooling/tests that peek that path
                name = (
                    data.get("zhs_name")
                    or data.get("atomic_official_name")
                    or data.get("atomic_translated_name")
                    or ""
                )
                safe_set, safe_num = self._mtgch_safe_names(set_code, number)
                (CACHE_DIR / f"zhname_{safe_set}_{safe_num}.txt").write_text(
                    name, encoding="utf-8"
                )
            return data
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 404 and self.use_disk_cache:
                neg_path.write_text("", encoding="utf-8")
            elif self.use_disk_cache and cache_path.exists():
                try:
                    return json.loads(cache_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            return None
        except (requests.RequestException, json.JSONDecodeError, ValueError):
            # Transient network/5xx/parse: do not write negative sentinel
            if self.use_disk_cache and cache_path.exists():
                try:
                    return json.loads(cache_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            return None

    def fetch_zh_name(self, set_code: str, number: str) -> str:
        data = self.fetch_mtgch_card(set_code, number)
        if not data:
            return ""
        return (
            data.get("zhs_name")
            or data.get("atomic_official_name")
            or data.get("atomic_translated_name")
            or ""
        )

    def resolve_images(
        self,
        set_code: str,
        number: str,
        lang: str,
        preferred: str | None = None,
        scryfall_card: dict[str, Any] | None = None,
    ) -> tuple[dict[str, str], str]:
        """Pick image URLs for snapshots (hotlinks only).

        Returns (image_dict, art_lang) where art_lang is the face language of
        the chosen art ("zhs" / "en" / ...), set from the resolution path —
        not inferred from URL shape (Scryfall URLs have no /zhs/ segment).

        Order of preference:
        1. For lang=zhs: Chinese art (mtgch zhs_image_uris, or Scryfall zhs printing)
           — inventory language wins over image_cdn host preference.
        2. Preferred CDN (site_config image_cdn: mtgch | scryfall)
        3. The other CDN as fallback

        Example: pip/717 has no Scryfall zhs printing (404) but mtgch has
        zhs_image_uris; Chinese stock must use those, not English Chaos Warp art.
        """
        pref = normalize_image_cdn(preferred or image_cdn_preference())
        empty = {"small": "", "normal": "", "large": ""}

        def has_img(imgs: dict[str, str]) -> bool:
            return bool(imgs.get("normal") or imgs.get("small"))

        def norm_art(art: str, default: str) -> str:
            a = (art or default or "en").strip()
            return "zhs" if a == "zh" else a

        def from_scry(
            card: dict[str, Any] | None = None, *, pick_lang: str | None = None
        ) -> tuple[dict[str, str], str]:
            c = card if card is not None else scryfall_card
            if c is None:
                try:
                    c = self.fetch_card(set_code, number, lang)
                except (requests.RequestException, json.JSONDecodeError, ValueError):
                    c = None
            c = c or {}
            pl = pick_lang if pick_lang is not None else lang
            imgs = pick_images(c, lang=pl)
            # Scryfall card.lang is authoritative for face language when present
            return imgs, norm_art(str(c.get("lang") or pl or "en"), "en")

        def from_mtgch(
            *, pick_lang: str | None = None, require_zhs_uris: bool = False
        ) -> tuple[dict[str, str], str]:
            """mtgch fetch. require_zhs_uris=True: only zhs_image_uris (strict Chinese face).

            Callers never use pick_lang='zhs' without require_zhs_uris — that path
            is handled exclusively by require_zhs_uris=True above.
            """
            data = self.fetch_mtgch_card(set_code, number)
            if not data:
                return empty, ""
            if require_zhs_uris:
                zhs = _uris_to_image(data.get("zhs_image_uris"))
                return (zhs, "zhs") if zhs else (empty, "")
            pl = pick_lang if pick_lang is not None else lang
            imgs = pick_images(data, lang=pl)
            return imgs, norm_art(str(data.get("lang") or pl or "en"), "en")

        def preferred_cdn_chain(
            *, pick_lang: str, art_default: str
        ) -> tuple[dict[str, str], str]:
            """Try preferred CDN then the other; normalize empty art to art_default."""
            if pref == IMAGE_CDN_MTGCH:
                order = (
                    lambda: from_mtgch(pick_lang=pick_lang),
                    lambda: from_scry(pick_lang=pick_lang),
                )
            else:
                order = (
                    lambda: from_scry(pick_lang=pick_lang),
                    lambda: from_mtgch(pick_lang=pick_lang),
                )
            imgs, art = order[0]()
            if has_img(imgs):
                return imgs, norm_art(art, art_default)
            imgs, art = order[1]()
            return imgs, norm_art(art, art_default) if has_img(imgs) else art_default

        # --- Chinese listing: prefer Chinese face art first ---
        if lang == "zhs":
            imgs, art = from_mtgch(require_zhs_uris=True)
            if has_img(imgs):
                return imgs, "zhs"
            # Scryfall Chinese printing only (not the en fallback card)
            if scryfall_card and scryfall_card.get("lang") in ("zhs", "zh"):
                imgs, art = from_scry(scryfall_card, pick_lang="zhs")
                if has_img(imgs):
                    return imgs, "zhs"
            # No Chinese face available — English art via preferred CDN
            return preferred_cdn_chain(pick_lang="en", art_default="en")

        # --- Non-zhs: preferred CDN first ---
        return preferred_cdn_chain(pick_lang=lang, art_default=lang or "en")


def load_previous_enrichment(
    output_path: Path, list_key: str = "cards"
) -> dict[str, dict[str, Any]]:
    """用已有 output 按 set|number|lang 复用元数据（加速重建）。

    list_key: cards.json 用 'cards'，wants.json 用 'wants'。
    """
    if not output_path.exists():
        return {}
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    cache: dict[str, dict[str, Any]] = {}
    for c in data.get(list_key) or []:
        if c.get("error"):
            continue
        key = f"{(c.get('set') or '').lower()}|{c.get('number')}|{c.get('lang')}"
        cache[key] = c
    return cache


def _uris_to_image(uris: dict[str, Any] | None) -> dict[str, str] | None:
    if not uris or not isinstance(uris, dict):
        return None
    small = (uris.get("small") or uris.get("normal") or "") or ""
    normal = (uris.get("normal") or uris.get("small") or "") or ""
    large = (uris.get("large") or uris.get("normal") or uris.get("small") or "") or ""
    if not (small or normal):
        return None
    return {"small": small, "normal": normal, "large": large}


def pick_images(card: dict[str, Any], lang: str = "en") -> dict[str, str]:
    """Extract small/normal/large image URLs from Scryfall- or mtgch-shaped JSON.

    For lang=zhs prefer zhs_image_uris when present (mtgch Chinese art).
    """
    empty = {"small": "", "normal": "", "large": ""}
    if not card:
        return empty
    prefer_zhs = lang == "zhs"
    if prefer_zhs:
        zhs = _uris_to_image(card.get("zhs_image_uris"))
        if zhs:
            return zhs
    top = _uris_to_image(card.get("image_uris"))
    if top:
        return top
    faces = card.get("card_faces") or card.get("faces") or []
    if isinstance(faces, list):
        for face in faces:
            if not isinstance(face, dict):
                continue
            if prefer_zhs:
                zhs = _uris_to_image(face.get("zhs_image_uris"))
                if zhs:
                    return zhs
            u = _uris_to_image(face.get("image_uris"))
            if u:
                return u
    # mtgch CardDescription-style single URL: only one size available, so
    # small/normal/large are identical (modal "large" is same quality as grid).
    if card.get("image_url"):
        u = str(card["image_url"])
        return {"small": u, "normal": u, "large": u}
    return empty


def pick_text(card: dict[str, Any]) -> tuple[str, str]:
    if card.get("card_faces"):
        texts = []
        types = []
        for face in card["card_faces"]:
            t = face.get("printed_text") or face.get("oracle_text") or ""
            if t:
                texts.append(t)
            ty = face.get("printed_type_line") or face.get("type_line") or ""
            if ty:
                types.append(ty)
        return "\n//\n".join(texts), " // ".join(types)

    text = card.get("printed_text") or card.get("oracle_text") or ""
    type_line = card.get("printed_type_line") or card.get("type_line") or ""
    return text, type_line


# 主类型（英文 type_line 子串匹配；一张牌可多个，如 Artifact Creature）
PRIMARY_TYPE_TAGS: list[tuple[str, str]] = [
    ("planeswalker", "planeswalker"),
    ("battle", "battle"),
    ("creature", "creature"),
    ("instant", "instant"),
    ("sorcery", "sorcery"),
    ("enchantment", "enchantment"),
    ("artifact", "artifact"),
    ("land", "land"),
]


def pick_type_line_en(card: dict[str, Any]) -> str:
    """Scryfall 根级 type_line 一般为英文，双面用 // 拼接。"""
    tl = (card.get("type_line") or "").strip()
    if tl:
        return tl
    faces = card.get("card_faces") or []
    parts = [(f.get("type_line") or "").strip() for f in faces]
    return " // ".join(p for p in parts if p)


def classify_types(type_line_en: str) -> list[str]:
    """从英文 type_line 得到可筛主类型标签。"""
    if not type_line_en:
        return ["other"]
    low = type_line_en.lower()
    found = [tag for key, tag in PRIMARY_TYPE_TAGS if key in low]
    return found or ["other"]


def pick_mana(card: dict[str, Any]) -> tuple[str, float]:
    """mana_cost 字符串 + cmc。双面/分体费用用 // 拼接（空面记为 -）。"""
    mc = (card.get("mana_cost") or "").strip()
    if not mc and card.get("card_faces"):
        costs = [(f.get("mana_cost") or "").strip() for f in card["card_faces"]]
        if any(costs):
            mc = " // ".join(c if c else "-" for c in costs)
    cmc_raw = card.get("cmc")
    try:
        cmc = float(cmc_raw) if cmc_raw is not None else 0.0
    except (TypeError, ValueError):
        cmc = 0.0
    return mc, cmc


def enrich_fields_from_scryfall(card: dict[str, Any]) -> dict[str, Any]:
    """从 Scryfall 卡对象提取展示/筛选用类型与费用字段。"""
    type_line_en = pick_type_line_en(card)
    mana_cost, cmc = pick_mana(card)
    return {
        "type_line_en": type_line_en,
        "types": classify_types(type_line_en),
        "mana_cost": mana_cost,
        "cmc": cmc,
    }


def looks_like_chinese_name(value: str | None) -> bool:
    """True if value contains CJK ideographs (usable as a Chinese card name).

    Rejects Latin-only mtgch fallbacks (e.g. atomic_official_name == English)
    so we never store English in name_zh and confuse displayName.

    Covers CJK Unified Ideographs (U+4E00–9FFF) + Extension A (U+3400–4DBF).
    Extension B+ (U+20000+, rare in MTG Chinese names) is not covered — add
    if a real card name ever needs it.
    """
    for ch in value or "":
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            return True
    return False


def base_from_cached(
    cached: dict[str, Any], set_code: str, number: str, lang: str
) -> dict[str, Any]:
    """从上一份 enrichment 缓存构建 base（inventory / wants 共用）。"""
    return {
        "name_en": cached.get("name_en", ""),
        "name_zh": cached.get("name_zh", ""),
        "name_printed": cached.get("name_printed", ""),
        "type_line": cached.get("type_line", ""),
        "type_line_en": cached.get("type_line_en", ""),
        "types": list(cached.get("types") or []),
        "mana_cost": cached.get("mana_cost", ""),
        "cmc": cached.get("cmc", 0),
        "text": cached.get("text", ""),
        "image": cached.get("image") or pick_images({}),
        "scryfall_uri": cached.get("scryfall_uri", ""),
        "set": cached.get("set") or set_code,
        "set_name": cached.get("set_name") or set_code.upper(),
        "number": cached.get("number") or number,
        "lang": cached.get("lang") or lang,
        "image_lang": cached.get("image_lang") or cached.get("lang") or lang,
        # Sticky markers (orthogonal): CDN host, Chinese-art attempt, zh name attempt
        "image_cdn_attempted": cached.get("image_cdn_attempted") or "",
        "zhs_art_attempted": bool(cached.get("zhs_art_attempted")),
        "zh_name_attempted": bool(cached.get("zh_name_attempted")),
    }


def base_from_card(
    card: dict[str, Any], client: ScryfallClient, set_code: str, number: str, lang: str
) -> dict[str, Any]:
    """从 Scryfall 卡对象构建 base（inventory / wants 共用，含中文名 + 图 CDN 偏好）。"""
    name_en = card.get("name") or ""
    name_printed = card.get("printed_name") or ""
    if not name_printed and card.get("card_faces"):
        name_printed = card["card_faces"][0].get("printed_name") or ""
    # zhs inventory: Scryfall may 404 Chinese printing and fall back to en card
    # (no printed_name) — still pull Chinese name from mtgch (e.g. pip/717).
    zh_name_attempted = False
    if lang == "zhs":
        name_zh = name_printed or ""
        if looks_like_chinese_name(name_zh):
            zh_name_attempted = True
        else:
            if client is not None and hasattr(client, "fetch_zh_name"):
                fetched = (client.fetch_zh_name(set_code, number) or "").strip()
                zh_name_attempted = True
                if looks_like_chinese_name(fetched):
                    name_zh = fetched
            if not looks_like_chinese_name(name_zh):
                name_zh = name_en
        # printed_name only falls back to Chinese when this is a zhs listing
        name_printed_out = name_printed or name_zh or name_en
    else:
        name_zh = ""
        if client is not None and hasattr(client, "fetch_zh_name"):
            fetched = (client.fetch_zh_name(set_code, number) or "").strip()
            zh_name_attempted = True
            if looks_like_chinese_name(fetched):
                name_zh = fetched
        name_printed_out = name_printed or name_en
    text, type_line = pick_text(card)
    meta = enrich_fields_from_scryfall(card)
    preferred = image_cdn_preference()
    if client is not None and hasattr(client, "resolve_images"):
        image, art_lang = client.resolve_images(
            set_code, number, lang, preferred, scryfall_card=card
        )
    else:
        # Tests may pass a stub client; fall back to Scryfall-shaped card images only.
        image = pick_images(card, lang=lang)
        art_lang = str(card.get("lang") or lang or "en")
        if art_lang == "zh":
            art_lang = "zhs"
    return {
        "name_en": name_en,
        "name_zh": name_zh,
        "name_printed": name_printed_out,
        "type_line": type_line,
        "type_line_en": meta["type_line_en"],
        "types": meta["types"],
        "mana_cost": meta["mana_cost"],
        "cmc": meta["cmc"],
        "text": text,
        "image": image,
        "scryfall_uri": card.get("scryfall_uri") or "",
        "set": card.get("set") or set_code,
        "set_name": card.get("set_name") or set_code.upper(),
        "number": card.get("collector_number") or number,
        "lang": card.get("lang") or lang,
        "image_lang": art_lang or lang,
        "image_cdn_attempted": preferred,
        "zhs_art_attempted": lang == "zhs",
        "zh_name_attempted": zh_name_attempted,
    }


def ensure_image_cdn(
    base: dict[str, Any],
    client: ScryfallClient,
    set_code: str,
    number: str,
    lang: str,
    preferred: str | None = None,
) -> dict[str, Any]:
    """Re-resolve when CDN preference or Chinese art is wrong.

    Control flag:
    - image_cdn_attempted: last preferred CDN host tried ("mtgch"|"scryfall");
      used for non-zhs sticky host preference (skip re-resolve when unchanged).

    Diagnostic only (not used for branching in this function):
    - zhs_art_attempted: still written True after a zhs resolve so snapshots /
      tooling can see that Chinese art was attempted; kept for historical rows
      already on disk. Do not treat as a control flag here.

    For lang=zhs with image_lang=="zhs": keep Chinese face even if image_cdn
    flips host (language/face wins over CDN preference).

    For lang=zhs still on English (or empty) art: always re-resolve so we pick
    up mtgch zhs_image_uris when Scryfall has no Chinese printing (e.g. pip/671).
    Disk cache makes this cheap for typical inventory sizes; if zhs-English
    volume grows large enough to slow builds, consider a re-resolve TTL first.
    """
    pref = normalize_image_cdn(preferred or image_cdn_preference())
    img = base.get("image") or {}
    url = str(img.get("normal") or img.get("small") or "")
    has_any = bool(url)
    art_lang = str(base.get("image_lang") or "")
    cdn_tried = str(base.get("image_cdn_attempted") or "")

    if lang == "zhs":
        # Already have Chinese face art → do not re-resolve for CDN host flip
        if has_any and art_lang == "zhs":
            return base
        # Missing Chinese face (first run, empty image, or prior English fallback):
        # re-attempt every build — Scryfall may 404 zhs while mtgch has art.
        base = dict(base)
        image, art = client.resolve_images(set_code, number, lang, pref)
        base["image"] = image
        base["image_lang"] = art or "en"
        base["zhs_art_attempted"] = True  # diagnostic only; see docstring
        base["image_cdn_attempted"] = pref
        return base

    # Non-zhs: preferred CDN sticky
    if image_dict_matches_cdn(base.get("image"), pref):
        return base
    if has_any and cdn_tried == pref:
        return base
    base = dict(base)
    image, art = client.resolve_images(set_code, number, lang, pref)
    base["image"] = image
    base["image_lang"] = art or lang
    base["image_cdn_attempted"] = pref
    return base


def ensure_zh_name(
    base: dict[str, Any],
    client: ScryfallClient,
    set_code: str,
    number: str,
    lang: str,
) -> dict[str, Any]:
    """Fill Chinese name from mtgch when missing or still non-CJK.

    Applies to every inventory language (en/zhs/ja/…): main-site displayName
    prefers name_zh whenever it differs from name_en, so English listings still
    need a Chinese name (e.g. one/370 en → 暗峰山崖).

    Sticky: zh_name_attempted (bool). Once True, do not re-query mtgch on later
    builds when still without a CJK name — mirrors image_cdn_attempted. Rows
    that lack the flag (old snapshots) get one repair pass, then stick.

    Only CJK names are accepted (looks_like_chinese_name); Latin-only mtgch
    fallbacks are ignored so displayName never treats English as Chinese.

    For lang=zhs only: also repair name_printed when it was missing / non-CJK.
    Non-zhs listings keep English name_printed (face language of the stock).
    """
    name_zh = (base.get("name_zh") or "").strip()
    name_en = (base.get("name_en") or "").strip()
    if looks_like_chinese_name(name_zh):
        if not base.get("zh_name_attempted"):
            base = dict(base)
            base["zh_name_attempted"] = True
        return base
    # Non-CJK placeholder (often English) — clear when sticking or after a failed fetch
    # so old snapshots do not keep Latin junk in name_zh.
    if base.get("zh_name_attempted"):
        if name_zh:
            base = dict(base)
            base["name_zh"] = ""
        return base
    if client is None or not hasattr(client, "fetch_zh_name"):
        return base
    zh = (client.fetch_zh_name(set_code, number) or "").strip()
    base = dict(base)
    base["zh_name_attempted"] = True
    if not looks_like_chinese_name(zh):
        base["name_zh"] = ""
        return base
    base["name_zh"] = zh
    if lang == "zhs":
        printed = (base.get("name_printed") or "").strip()
        if not printed or printed == name_en or not looks_like_chinese_name(printed):
            base["name_printed"] = zh
    return base
