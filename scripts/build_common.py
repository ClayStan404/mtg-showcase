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
    """用内容 md5 前 8 位更新 index.html 里 assets/<asset_filename>?v=... 的版本号。

    让自动部署的 cards-data.js / wants-data.js 内容变化即自动击穿浏览器缓存，
    无需手动 bump index.html 里的 ?v=N。app.js / style.css 也由 build 脚本统一 bump。
    """
    if not html_path.exists():
        return
    digest = hashlib.md5(content).hexdigest()[:8]
    text = html_path.read_text(encoding="utf-8")
    pattern = re.compile(rf"(assets/{re.escape(asset_filename)}\?v=)[^\"'\s]+")
    new_text, n = pattern.subn(rf"\g<1>{digest}", text)
    if n and new_text != text:
        html_path.write_text(new_text, encoding="utf-8")


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


def load_site_config() -> dict[str, Any]:
    if SITE_CONFIG.exists():
        try:
            return json.loads(SITE_CONFIG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            # site_config.json 损坏时回退默认配置，避免直接崩掉整轮 build
            print(f"⚠ site_config.json 解析失败，使用默认配置: {e}", file=sys.stderr)
    return {
        "title": "万智牌 Sales List",
        "subtitle": "实体卡展示 · 站外联系成交",
    }


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

    def fetch_card(self, set_code: str, number: str, lang: str) -> dict[str, Any] | None:
        api_lang = scryfall_lang(lang)
        cache_path = self._cache_path(set_code, number, api_lang)
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

        # 仅当返回数据的 lang 与请求 lang 一致时才缓存到 api_lang 路径。
        # 回退场景（如 ja 卡无日文印刷 -> 404 -> 取 en）下 data.lang != api_lang，
        # 不缓存，避免把英文数据写入 ja 缓存路径造成键与内容不符、且 Scryfall
        # 日后新增该印刷后无法自动刷新。
        if data is not None and self.use_disk_cache and data.get("lang") == api_lang:
            cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def fetch_zh_name(self, set_code: str, number: str) -> str:
        safe_set = re.sub(r"[^\w.-]", "_", set_code)
        safe_num = re.sub(r"[^\w.-]", "_", number)
        cache_path = CACHE_DIR / f"zhname_{safe_set}_{safe_num}.txt"
        if self.use_disk_cache and cache_path.exists():
            # 负结果也缓存（空文件作哨兵），避免每次重试失败的 mtgch 请求；同样受 TTL
            if time.time() - cache_path.stat().st_mtime < CACHE_TTL:
                return cache_path.read_text(encoding="utf-8").strip()

        url = f"https://mtgch.com/api/v1/card/{set_code}/{number}/"
        try:
            data = self.get(url, throttle=False).json()
            name = (
                data.get("zhs_name")
                or data.get("atomic_official_name")
                or data.get("atomic_translated_name")
                or ""
            )
            if self.use_disk_cache:
                # 仅在 API 正常返回时缓存正/负结果（有名字写名字，无名字写空文件作哨兵）
                cache_path.write_text(name, encoding="utf-8")
        except (requests.RequestException, json.JSONDecodeError, ValueError):
            # 瞬时故障（超时/5xx/非法 JSON）不缓存，否则会把“暂时拿不到”固化成 30 天阴性
            name = ""
        return name


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


def pick_images(card: dict[str, Any]) -> dict[str, str]:
    if card.get("image_uris"):
        uris = card["image_uris"]
        return {
            "small": uris.get("small", ""),
            "normal": uris.get("normal", ""),
            "large": uris.get("large", ""),
        }
    faces = card.get("card_faces") or []
    if faces and faces[0].get("image_uris"):
        uris = faces[0]["image_uris"]
        return {
            "small": uris.get("small", ""),
            "normal": uris.get("normal", ""),
            "large": uris.get("large", ""),
        }
    return {"small": "", "normal": "", "large": ""}


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
    }


def base_from_card(
    card: dict[str, Any], client: ScryfallClient, set_code: str, number: str, lang: str
) -> dict[str, Any]:
    """从 Scryfall 卡对象构建 base（inventory / wants 共用，含中文名 fetch）。"""
    name_en = card.get("name") or ""
    name_printed = card.get("printed_name") or ""
    if not name_printed and card.get("card_faces"):
        name_printed = card["card_faces"][0].get("printed_name") or ""
    if lang == "zhs":
        name_zh = name_printed or name_en
    else:
        name_zh = client.fetch_zh_name(set_code, number)
    text, type_line = pick_text(card)
    meta = enrich_fields_from_scryfall(card)
    return {
        "name_en": name_en,
        "name_zh": name_zh,
        "name_printed": name_printed or name_en,
        "type_line": type_line,
        "type_line_en": meta["type_line_en"],
        "types": meta["types"],
        "mana_cost": meta["mana_cost"],
        "cmc": meta["cmc"],
        "text": text,
        "image": pick_images(card),
        "scryfall_uri": card.get("scryfall_uri") or "",
        "set": card.get("set") or set_code,
        "set_name": card.get("set_name") or set_code.upper(),
        "number": card.get("collector_number") or number,
        "lang": card.get("lang") or lang,
        "image_lang": card.get("lang") or lang,
    }
