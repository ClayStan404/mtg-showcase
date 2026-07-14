#!/usr/bin/env python3
"""Parse inventory/*.txt -> enrich via Scryfall (+ mtgch) -> data/cards.json"""

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
from build_common import (  # noqa: E402
    ScryfallClient,
    base_from_cached,
    base_from_card,
    bump_cache_buster,
    load_previous_enrichment,
    load_site_config,
    payload_unchanged,
    pick_images,
    stable_payload_bytes,
)
from inventory_format import (  # noqa: E402
    META_RE,
    ParseError,
    card_line_to_fields,
    lang_label,
    slugify,
    validate_meta,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY_DIR = ROOT / "inventory"
DEFAULT_INVENTORY_FILE = ROOT / "inventory.txt"  # 兼容旧单文件
DEFAULT_OUTPUT = ROOT / "data" / "cards.json"


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

    with path.open(encoding="utf-8-sig") as fh:
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
                    "foil": is_foil,
                    "quantity": qty,
                    "source_file": path.name,
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

    # 跨文件合并：同 seller 的相同印刷可能出现在多个 sheet/txt（write_sheets 按
    # sheet 拆文件不改 seller_id），按 card_id 键合并数量，避免重复 card_id。
    merged_all: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for e in all_entries:
        key = f"{e['seller_id']}|{e['set']}|{e['number']}|{e['lang']}|{'foil' if e['foil'] else 'nf'}"
        if key in merged_all:
            merged_all[key]["quantity"] += e["quantity"]
        else:
            merged_all[key] = e
    return list(merged_all.values())


def card_id(entry: dict[str, Any]) -> str:
    return (
        f"{entry['seller_id']}-"
        f"{entry['set']}-{entry['number']}-{entry['lang']}-"
        f"{'f' if entry['foil'] else 'nf'}"
    )


def _num_key(num: str) -> tuple:
    m = re.match(r"^(\d+)", str(num))
    return (int(m.group(1)) if m else 0, str(num))


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
            base = base_from_cached(cached, set_code, number, lang)

        if base is None:
            try:
                card = client.fetch_card(set_code, number, lang)
            except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
                # 捕获 JSONDecodeError 等非 HTTPError 异常，避免单卡崩溃整个构建
                print(f"  ! 获取失败 {set_code} {number} {lang}: {exc}", file=sys.stderr)
                card = None
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
                        "scryfall_uri": "",
                        "image_lang": lang,
                        "error": "not_found",
                    }
                )
                continue

            base = base_from_card(card, client, set_code, number, lang)

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
                "image_lang": base.get("image_lang") or entry["lang"],
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

    # 静态资源的 cache buster 无论数据是否变化都要 bump
    # （app.js / style.css 可能被手动修改但卡数据没变）
    for static_file in ("app.js", "style.css"):
        p = ROOT / "assets" / static_file
        if p.exists():
            bump_cache_buster(ROOT / "index.html", static_file, p.read_bytes())

    # 先写前端内嵌 JS（即使 JSON 无变化也写，防 JS 被误删后不重建）
    js_path = ROOT / "assets" / "cards-data.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    js_bytes = f"window.__MTG_DATA__={compact};\n".encode()
    js_path.write_bytes(js_bytes)
    # cache buster 基于剔除 generated_at 的稳定内容，避免每小时时间戳变化导致 ?v= 抖动
    bump_cache_buster(ROOT / "index.html", "cards-data.js", stable_payload_bytes(payload, "window.__MTG_DATA__"))
    print(f"已写入 {js_path}")

    if payload_unchanged(args.output, payload):
        print(f"数据无变化，跳过写入 {args.output}")
        return 0
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"已写入 {args.output} （{payload['count']} 种 / 共 {payload['total_quantity']} 张 · "
        f"{len(sellers)} 位出售人 · {len(cities)} 个城市）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
