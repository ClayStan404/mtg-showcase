#!/usr/bin/env python3
"""Parse wants/*.txt → assets/wants-data.js (+ data/wants.json)

统一求购行（合并「指定 / 可替」）:
  [Nx] set number [lang] [foil] [must] [| 备注]

  lang: e/z/j/o（空=e）
  foil: 0/1（空=0）
  must: 0=其他版本也可以，1=必须此印刷（空=0）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inventory_format import (  # noqa: E402
    ParseError,
    lang_label,
    slugify,
    want_line_to_fields,
)
from build_data import (  # noqa: E402
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

            # 兼容旧 any 行：提示后跳过
            if line.lower().startswith("any ") or line.lower().startswith("any\t"):
                print(
                    f"[warn] {path.name}:{line_num} 已弃用 any 行，请改为 "
                    f"「系列 编号 语言 闪 0」表示可替版本，跳过: {line}",
                    file=sys.stderr,
                )
                continue

            try:
                set_code, number, lang, foil, qty, must, note = want_line_to_fields(line)
            except ParseError as e:
                print(f"[warn] {path.name}:{line_num} {e}，跳过: {line}", file=sys.stderr)
                continue

            buyer_name = buyer or source
            buyer_id = slugify(buyer_name, source)
            # kind: exact=必须此版，flex=可替
            kind = "exact" if must else "flex"
            entries.append(
                {
                    "kind": kind,
                    "must": must,
                    "set": set_code,
                    "number": number,
                    "lang": lang,
                    "foil": foil,
                    "quantity": qty,
                    "note": note,
                    "buyer": buyer_name,
                    "buyer_id": buyer_id,
                    "city": city,
                    "contact": contact,
                    "source_file": path.name,
                    "source_line": line_num,
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


def enrich_wants(entries: list[dict[str, Any]], client: ScryfallClient) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    total = len(entries)
    for i, e in enumerate(entries, 1):
        print(
            f"[{i}/{total}] {e['buyer']} · {e['set']} {e['number']} "
            f"{'必须' if e['must'] else '可替'}",
            flush=True,
        )
        card = client.fetch_card(e["set"], e["number"], e["lang"])
        wid = (
            f"{e['buyer_id']}-{e['set']}-{e['number']}-{e['lang']}-"
            f"{'f' if e['foil'] else 'nf'}-{'1' if e['must'] else '0'}"
        )
        if not card:
            out.append(
                {
                    "id": wid,
                    "kind": e["kind"],
                    "must": e["must"],
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
                "id": wid,
                "kind": e["kind"],
                "must": e["must"],
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
