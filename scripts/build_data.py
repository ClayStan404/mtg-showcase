#!/usr/bin/env python3
"""Parse inventory/*.txt → enrich via Scryfall (+ mtgch) → data/cards.json"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inventory_format import (  # noqa: E402
    LANG_LABEL,
    ParseError,
    card_line_to_fields,
    lang_label,
    scryfall_lang,
    slugify,
    validate_meta,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY_DIR = ROOT / "inventory"
DEFAULT_INVENTORY_FILE = ROOT / "inventory.txt"  # 兼容旧单文件
DEFAULT_OUTPUT = ROOT / "data" / "cards.json"
SITE_CONFIG = ROOT / "site_config.json"
CACHE_DIR = ROOT / ".cache" / "scryfall"

# # seller: 昵称  /  # city: 上海  /  # contact: ...
META_RE = re.compile(
    r"^#\s*(seller|nickname|nick|city|contact|wechat)\s*[:=：]\s*(.+?)\s*$",
    re.I,
)

REQUEST_GAP = 0.12
USER_AGENT = "MTGShowcase/1.0 (personal inventory; github pages)"


def load_site_config() -> dict[str, Any]:
    if SITE_CONFIG.exists():
        return json.loads(SITE_CONFIG.read_text(encoding="utf-8"))
    return {
        "title": "万智牌 Sales List",
        "subtitle": "实体卡展示 · 站外联系成交",
        "contact": {
            "wechat": "",
            "email": "",
            "note": "",
        },
    }

def discover_inventory_files(inventory_dir: Path, legacy_file: Path) -> list[Path]:
    files: list[Path] = []
    if inventory_dir.is_dir():
        files = sorted(
            p
            for p in inventory_dir.glob("*.txt")
            if p.is_file() and not p.name.startswith("_")
        )
    if files:
        return files
    if legacy_file.is_file():
        return [legacy_file]
    return []


def parse_inventory_file(path: Path) -> list[dict[str, Any]]:
    """解析单个库存文件。文件头 # seller: / # city: 作用于全文。"""
    seller = ""
    city = ""
    contact = ""
    source = path.stem if path.name != "inventory.txt" else "default"

    merged: OrderedDict[str, dict[str, Any]] = OrderedDict()

    with path.open(encoding="utf-8") as fh:
        for line_num, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue

            if line.startswith("#"):
                m = META_RE.match(line)
                if m:
                    key = m.group(1).lower()
                    val = m.group(2).strip()
                    if key in ("seller", "nickname", "nick"):
                        seller = val
                    elif key == "city":
                        city = val
                    elif key in ("contact", "wechat"):
                        contact = val
                continue

            parts = line.split()
            try:
                set_code, number, lang, is_foil, qty = card_line_to_fields(parts)
            except ParseError as e:
                print(f"[warn] {path.name}:{line_num} {e}，跳过: {raw.rstrip()}", file=sys.stderr)
                continue

            seller_name = seller or source
            seller_id = slugify(seller_name, source)
            key = f"{seller_id}|{set_code}|{number}|{lang}|{'foil' if is_foil else 'nf'}"

            if key in merged:
                merged[key]["quantity"] += qty
            else:
                merged[key] = {
                    "set": set_code,
                    "number": number,
                    "lang": lang,
                    "lang_raw": lang,
                    "foil": is_foil,
                    "quantity": qty,
                    "source_file": path.name,
                    "source_line": line_num,
                    "seller": seller_name,
                    "seller_id": seller_id,
                    "city": city,
                    "contact": contact,
                }

    meta_errors = validate_meta(
        {"seller": seller, "city": city, "contact": contact}, path.name
    )
    if meta_errors:
        raise ParseError("; ".join(meta_errors))

    return list(merged.values())


def parse_all_inventories(inventory_dir: Path, legacy_file: Path) -> list[dict[str, Any]]:
    files = discover_inventory_files(inventory_dir, legacy_file)
    if not files:
        raise FileNotFoundError(
            f"未找到库存文件。请在 {inventory_dir}/ 下添加 *.txt，或提供 {legacy_file.name}"
        )

    all_entries: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in files:
        try:
            entries = parse_inventory_file(path)
            print(f"  · {path.name}: {len(entries)} 种")
            all_entries.extend(entries)
        except ParseError as e:
            errors.append(str(e))
    if errors:
        print(f"\n❌ 校验失败（{len(errors)} 个问题）：", file=sys.stderr)
        for e in errors:
            print(f"  · {e}", file=sys.stderr)
        raise SystemExit(1)
    return all_entries


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

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        self._throttle()
        resp = self.session.get(url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    def _cache_path(self, set_code: str, number: str, lang: str) -> Path:
        safe_num = re.sub(r"[^\w.-]", "_", number)
        return CACHE_DIR / f"{set_code}_{safe_num}_{lang}.json"

    def fetch_card(self, set_code: str, number: str, lang: str) -> dict[str, Any] | None:
        api_lang = scryfall_lang(lang)
        cache_path = self._cache_path(set_code, number, api_lang)
        if self.use_disk_cache and cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

        urls = [f"https://api.scryfall.com/cards/{set_code}/{number}/{api_lang}"]
        if api_lang != "en":
            urls.append(f"https://api.scryfall.com/cards/{set_code}/{number}")

        data = None
        for url in urls:
            try:
                data = self.get(url).json()
                break
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    continue
                raise

        if data is not None and self.use_disk_cache:
            cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def fetch_zh_name(self, set_code: str, number: str) -> str:
        cache_path = CACHE_DIR / f"zhname_{set_code}_{re.sub(r'[^\w.-]', '_', number)}.txt"
        if self.use_disk_cache and cache_path.exists():
            return cache_path.read_text(encoding="utf-8").strip()

        url = f"https://mtgch.com/api/v1/card/{set_code}/{number}/"
        try:
            data = self.get(url).json()
            name = (
                data.get("zhs_name")
                or data.get("atomic_official_name")
                or data.get("atomic_translated_name")
                or ""
            )
        except Exception:
            name = ""

        if self.use_disk_cache and name:
            cache_path.write_text(name, encoding="utf-8")
        return name


def load_previous_enrichment(output_path: Path) -> dict[str, dict[str, Any]]:
    """用已有 cards.json 按 set|number|lang 复用元数据（加速重建）。"""
    if not output_path.exists():
        return {}
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    cache: dict[str, dict[str, Any]] = {}
    for c in data.get("cards") or []:
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
    """mana_cost 字符串 + cmc。双面/分体费用用 // 拼接（空面记为 —）。"""
    mc = (card.get("mana_cost") or "").strip()
    if not mc and card.get("card_faces"):
        costs = [(f.get("mana_cost") or "").strip() for f in card["card_faces"]]
        if any(costs):
            mc = " // ".join(c if c else "—" for c in costs)
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


def card_id(entry: dict[str, Any]) -> str:
    return (
        f"{entry['seller_id']}-"
        f"{entry['set']}-{entry['number']}-{entry['lang']}-"
        f"{'f' if entry['foil'] else 'nf'}"
    )


def enrich(
    entries: list[dict[str, Any]],
    client: ScryfallClient,
    prev: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    total = len(entries)

    for i, entry in enumerate(entries, 1):
        set_code = entry["set"]
        number = entry["number"]
        lang = entry["lang"]
        prev_key = f"{set_code}|{number}|{lang}"
        print(
            f"[{i}/{total}] {entry['seller']} · {set_code} {number} {lang}"
            f"{' foil' if entry['foil'] else ''}",
            flush=True,
        )

        base: dict[str, Any] | None = None
        cached = prev.get(prev_key)
        # 缺 types/cmc 的旧缓存不可复用（需重新拉 Scryfall）
        if (
            cached
            and not cached.get("error")
            and "types" in cached
            and "cmc" in cached
            and "mana_cost" in cached
        ):
            base = {
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
            }

        if base is None:
            card = client.fetch_card(set_code, number, lang)
            if not card:
                print(f"  ! 未找到: {set_code} {number} {lang}", file=sys.stderr)
                results.append(
                    {
                        "id": card_id(entry),
                        "set": set_code,
                        "set_name": set_code.upper(),
                        "number": number,
                        "lang": lang,
                        "lang_label": lang_label(lang),
                        "foil": entry["foil"],
                        "quantity": entry["quantity"],
                        "seller": entry["seller"],
                        "seller_id": entry["seller_id"],
                        "city": entry["city"],
                        "contact": entry["contact"],
                        "source_file": entry["source_file"],
                        "name_en": "",
                        "name_zh": "",
                        "name_printed": "",
                        "type_line": "",
                        "type_line_en": "",
                        "types": [],
                        "mana_cost": "",
                        "cmc": 0,
                        "text": "",
                        "image": pick_images({}),
                        "error": "not_found",
                    }
                )
                continue

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
            base = {
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
            }

        results.append(
            {
                "id": card_id(entry),
                "set": base["set"],
                "set_name": base["set_name"],
                "number": base["number"],
                # 筛选/展示以库存为准（other 用英文图作回退）
                "lang": entry["lang"],
                "lang_label": lang_label(entry["lang"]),
                "foil": entry["foil"],
                "quantity": entry["quantity"],
                "seller": entry["seller"],
                "seller_id": entry["seller_id"],
                "city": entry["city"],
                "contact": entry["contact"],
                "source_file": entry["source_file"],
                "name_en": base["name_en"],
                "name_zh": base["name_zh"],
                "name_printed": base["name_printed"],
                "type_line": base["type_line"],
                "type_line_en": base.get("type_line_en") or "",
                "types": list(base.get("types") or []),
                "mana_cost": base.get("mana_cost") or "",
                "cmc": base.get("cmc") if base.get("cmc") is not None else 0,
                "text": base["text"],
                "image": base["image"],
                "scryfall_uri": base["scryfall_uri"],
            }
        )

    results.sort(
        key=lambda c: (
            c.get("city") or "",
            c.get("seller") or "",
            c["set"],
            _num_key(c["number"]),
            c["lang"],
            not c["foil"],
        )
    )
    return results


def _num_key(num: str) -> tuple:
    m = re.match(r"^(\d+)", str(num))
    return (int(m.group(1)) if m else 0, str(num))


def main() -> int:
    parser = argparse.ArgumentParser(description="从 inventory 生成网站用 cards.json")
    parser.add_argument(
        "-i",
        "--inventory-dir",
        type=Path,
        default=DEFAULT_INVENTORY_DIR,
        help="库存目录（默认 inventory/，读取其中 *.txt）",
    )
    parser.add_argument(
        "--legacy-file",
        type=Path,
        default=DEFAULT_INVENTORY_FILE,
        help="兼容旧的单文件 inventory.txt",
    )
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-cache", action="store_true", help="禁用 Scryfall 磁盘缓存")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="只解析库存、不请求网络（用于 PR 校验）",
    )
    args = parser.parse_args()

    print("读取库存…")
    try:
        entries = parse_all_inventories(args.inventory_dir, args.legacy_file)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    if not entries:
        print("没有有效库存行", file=sys.stderr)
        return 1

    print(f"合计 {len(entries)} 种（已按出售人+印刷合并重复）")

    if args.validate_only:
        sellers = sorted({e["seller"] for e in entries})
        cities = sorted({e["city"] for e in entries if e["city"]})
        print(f"校验通过 · 出售人 {len(sellers)} · 城市 {len(cities)}")
        return 0

    prev = load_previous_enrichment(args.output)
    client = ScryfallClient(use_disk_cache=not args.no_cache)
    cards = enrich(entries, client, prev)

    sellers = sorted({c["seller"] for c in cards if c.get("seller")})
    cities = sorted({c["city"] for c in cards if c.get("city")})

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "site": load_site_config(),
        "count": len(cards),
        "total_quantity": sum(c.get("quantity", 0) for c in cards),
        "sellers": sellers,
        "cities": cities,
        "cards": cards,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"已写入 {args.output} （{payload['count']} 种 / 共 {payload['total_quantity']} 张 · "
        f"{len(sellers)} 位出售人 · {len(cities)} 个城市）"
    )

    # 同步生成前端内嵌数据，减少浏览器额外请求 cards.json（代理/DNS 环境下更稳）
    js_path = ROOT / "assets" / "cards-data.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    js_path.write_text(f"window.__MTG_DATA__={compact};\n", encoding="utf-8")
    print(f"已写入 {js_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
