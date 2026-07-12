#!/usr/bin/env python3
"""Parse wants/*.txt → assets/wants-data.js (+ data/wants.json)

求购两种行：
  1) 指定印刷：[Nx] set number [lang] [foil]   （同 inventory）
  2) 任意版本：any <牌名> [数量] [| 备注]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inventory_format import (  # noqa: E402
    ParseError,
    card_line_to_fields,
    lang_label,
    scryfall_lang,
    slugify,
)

# reuse Scryfall client from build_data
from build_data import (  # noqa: E402
    CACHE_DIR,
    REQUEST_GAP,
    USER_AGENT,
    ScryfallClient,
    load_site_config,
    pick_images,
    pick_text,
)

ROOT = Path(__file__).resolve().parents[1]
WANTS_DIR = ROOT / "wants"
OUT_JSON = ROOT / "data" / "wants.json"
OUT_JS = ROOT / "assets" / "wants-data.js"

META_RE = re.compile(
    r"^#\s*(buyer|seller|nickname|nick|city|contact|wechat)\s*[:=：]\s*(.+?)\s*$",
    re.I,
)
ANY_RE = re.compile(
    r"^any\s+(.+?)(?:\s+(\d+))?\s*(?:\|\s*(.*))?$",
    re.I,
)


def parse_want_file(path: Path) -> list[dict[str, Any]]:
    buyer = ""
    city = ""
    contact = ""
    source = path.stem
    entries: list[dict[str, Any]] = []

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
                    if key in ("buyer", "seller", "nickname", "nick"):
                        buyer = val
                    elif key == "city":
                        city = val
                    elif key in ("contact", "wechat"):
                        contact = val
                continue

            buyer_name = buyer or source
            buyer_id = slugify(buyer_name, source)
            base_meta = {
                "buyer": buyer_name,
                "buyer_id": buyer_id,
                "city": city,
                "contact": contact,
                "source_file": path.name,
                "source_line": line_num,
            }

            # any-version
            if line.lower().startswith("any ") or line.lower().startswith("any\t"):
                m = ANY_RE.match(line)
                if not m:
                    print(f"[warn] {path.name}:{line_num} any 格式错误，跳过: {line}", file=sys.stderr)
                    continue
                name_q = m.group(1).strip()
                qty = int(m.group(2) or "1")
                note = (m.group(3) or "").strip()
                if not name_q:
                    print(f"[warn] {path.name}:{line_num} any 缺牌名", file=sys.stderr)
                    continue
                entries.append(
                    {
                        **base_meta,
                        "kind": "any",
                        "name_query": name_q,
                        "quantity": max(1, qty),
                        "note": note,
                    }
                )
                continue

            # specific printing
            try:
                set_code, number, lang, foil, qty = card_line_to_fields(line.split())
            except ParseError as e:
                print(f"[warn] {path.name}:{line_num} {e}，跳过: {line}", file=sys.stderr)
                continue
            entries.append(
                {
                    **base_meta,
                    "kind": "printing",
                    "set": set_code,
                    "number": number,
                    "lang": lang,
                    "foil": foil,
                    "quantity": qty,
                    "note": "",
                }
            )

    return entries


def parse_all_wants(wants_dir: Path) -> list[dict[str, Any]]:
    if not wants_dir.is_dir():
        return []
    files = sorted(
        p for p in wants_dir.glob("*.txt") if p.is_file() and not p.name.startswith("_")
    )
    all_e: list[dict[str, Any]] = []
    for p in files:
        es = parse_want_file(p)
        print(f"  · {p.name}: {len(es)} 条")
        all_e.extend(es)
    return all_e


def fetch_named(client: ScryfallClient, query: str) -> dict[str, Any] | None:
    """Fuzzy named lookup for any-version wants."""
    url = f"https://api.scryfall.com/cards/named?fuzzy={quote(query)}"
    try:
        return client.get(url).json()
    except Exception as e:
        print(f"  ! named 未找到: {query} ({e})", file=sys.stderr)
        return None


def enrich_wants(entries: list[dict[str, Any]], client: ScryfallClient) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    total = len(entries)
    for i, e in enumerate(entries, 1):
        kind = e["kind"]
        print(f"[{i}/{total}] {e['buyer']} · {kind} · {e.get('set') or e.get('name_query')}", flush=True)

        if kind == "printing":
            card = client.fetch_card(e["set"], e["number"], e["lang"])
            if not card:
                out.append(
                    {
                        "id": f"{e['buyer_id']}-p-{e['set']}-{e['number']}-{e['lang']}-{'f' if e['foil'] else 'nf'}",
                        "kind": "printing",
                        "buyer": e["buyer"],
                        "buyer_id": e["buyer_id"],
                        "city": e["city"],
                        "contact": e["contact"],
                        "quantity": e["quantity"],
                        "note": e.get("note") or "",
                        "set": e["set"],
                        "set_name": e["set"].upper(),
                        "number": e["number"],
                        "lang": e["lang"],
                        "lang_label": lang_label(e["lang"]),
                        "foil": e["foil"],
                        "name_en": "",
                        "name_zh": "",
                        "name_printed": "",
                        "type_line": "",
                        "text": "",
                        "image": {"small": "", "normal": "", "large": ""},
                        "error": "not_found",
                        "source_file": e["source_file"],
                    }
                )
                continue
            name_en = card.get("name") or ""
            name_printed = card.get("printed_name") or name_en
            if e["lang"] == "zhs":
                name_zh = name_printed or name_en
            else:
                name_zh = client.fetch_zh_name(e["set"], e["number"])
            text, type_line = pick_text(card)
            out.append(
                {
                    "id": f"{e['buyer_id']}-p-{e['set']}-{e['number']}-{e['lang']}-{'f' if e['foil'] else 'nf'}",
                    "kind": "printing",
                    "buyer": e["buyer"],
                    "buyer_id": e["buyer_id"],
                    "city": e["city"],
                    "contact": e["contact"],
                    "quantity": e["quantity"],
                    "note": e.get("note") or "",
                    "set": card.get("set") or e["set"],
                    "set_name": card.get("set_name") or e["set"].upper(),
                    "number": card.get("collector_number") or e["number"],
                    "lang": e["lang"],
                    "lang_label": lang_label(e["lang"]),
                    "foil": e["foil"],
                    "name_en": name_en,
                    "name_zh": name_zh,
                    "name_printed": name_printed,
                    "type_line": type_line,
                    "text": text,
                    "image": pick_images(card),
                    "scryfall_uri": card.get("scryfall_uri") or "",
                    "source_file": e["source_file"],
                }
            )
        else:
            # any version
            card = fetch_named(client, e["name_query"])
            name_en = (card or {}).get("name") or e["name_query"]
            name_printed = (card or {}).get("printed_name") or name_en
            name_zh = ""
            if card:
                # try chinese via set/number if available
                st = card.get("set") or ""
                num = card.get("collector_number") or ""
                if st and num:
                    name_zh = client.fetch_zh_name(st, num)
            text, type_line = pick_text(card) if card else ("", "")
            slug = slugify(e["name_query"], "card")
            out.append(
                {
                    "id": f"{e['buyer_id']}-a-{slug}",
                    "kind": "any",
                    "buyer": e["buyer"],
                    "buyer_id": e["buyer_id"],
                    "city": e["city"],
                    "contact": e["contact"],
                    "quantity": e["quantity"],
                    "note": e.get("note") or "",
                    "name_query": e["name_query"],
                    "name_en": name_en,
                    "name_zh": name_zh,
                    "name_printed": name_printed,
                    "set": (card or {}).get("set") or "",
                    "set_name": (card or {}).get("set_name") or "任意版本",
                    "number": (card or {}).get("collector_number") or "",
                    "lang": "any",
                    "lang_label": "任意",
                    "foil": False,
                    "type_line": type_line,
                    "text": text,
                    "image": pick_images(card or {}),
                    "scryfall_uri": (card or {}).get("scryfall_uri") or "",
                    "source_file": e["source_file"],
                    "error": None if card else "not_found",
                }
            )

    out.sort(key=lambda c: (c.get("city") or "", c.get("buyer") or "", c.get("name_en") or ""))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="生成求购 wants 数据")
    parser.add_argument("-i", "--wants-dir", type=Path, default=WANTS_DIR)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    print("读取求购 wants/ …")
    entries = parse_all_wants(args.wants_dir)
    if not entries:
        print("无求购条目，写入空数据")
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "site": load_site_config(),
            "count": 0,
            "total_quantity": 0,
            "buyers": [],
            "cities": [],
            "wants": [],
        }
    else:
        print(f"合计 {len(entries)} 条")
        if args.validate_only:
            print("校验通过（未联网）")
            return 0
        client = ScryfallClient(use_disk_cache=not args.no_cache)
        wants = enrich_wants(entries, client)
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "site": load_site_config(),
            "count": len(wants),
            "total_quantity": sum(w.get("quantity", 0) for w in wants),
            "buyers": sorted({w["buyer"] for w in wants if w.get("buyer")}),
            "cities": sorted({w["city"] for w in wants if w.get("city")}),
            "wants": wants,
        }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUT_JS.write_text(f"window.__MTG_WANTS__={compact};\n", encoding="utf-8")
    print(f"已写入 {OUT_JSON} 与 {OUT_JS} （{payload['count']} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
