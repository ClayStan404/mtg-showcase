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
    stable_payload_bytes,
)
from inventory_format import (  # noqa: E402
    ParseError,
    lang_label,
    slugify,
    validate_meta,
    want_line_to_fields,
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
                }
            )

    meta_errors = validate_meta(
        {"buyer": buyer, "city": city, "contact": contact},
        path.name,
        required=("buyer", "city", "contact"),
    )
    if meta_errors:
        raise ParseError("; ".join(meta_errors))

    return entries


def parse_all_wants(wants_dir: Path) -> list[dict[str, Any]]:
    if not wants_dir.is_dir():
        return []
    files = sorted(
        p for p in wants_dir.glob("*.txt") if p.is_file() and not p.name.startswith("_")
    )
    all_e: list[dict[str, Any]] = []
    errors: list[str] = []
    for p in files:
        try:
            es = parse_want_file(p)
            print(f"  · {p.name}: {len(es)} 条")
            all_e.extend(es)
        except ParseError as e:
            errors.append(str(e))
    if errors:
        print(f"\n❌ 校验失败（{len(errors)} 个问题）：", file=sys.stderr)
        for e in errors:
            print(f"  · {e}", file=sys.stderr)
        raise SystemExit(1)
    return all_e


def enrich_wants(
    entries: list[dict[str, Any]],
    client: ScryfallClient,
    prev: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    total = len(entries)
    for i, e in enumerate(entries, 1):
        set_code = e["set"]
        number = e["number"]
        lang = e["lang"]
        prev_key = f"{set_code}|{number}|{lang}"
        print(
            f"[{i}/{total}] {e['buyer']} · {set_code} {number} {lang}"
            f"{' 必须' if e['must'] else ' 可替'}",
            flush=True,
        )
        wid = (
            f"{e['buyer_id']}-{set_code}-{number}-{lang}-"
            f"{'f' if e['foil'] else 'nf'}-{'1' if e['must'] else '0'}"
        )

        # 复用上一份 wants.json 的富化结果（加速重建，对齐 build_data 的两层增量）
        base: dict[str, Any] | None = None
        cached = prev.get(prev_key)
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
                # 捕获网络/解析异常，避免单卡崩溃整个 wants 构建
                print(f"  ! 获取失败 {set_code} {number} {lang}: {exc}", file=sys.stderr)
                card = None
            if not card:
                print(f"  ! 未找到: {set_code} {number} {lang}", file=sys.stderr)
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
                        "set": set_code,
                        "set_name": set_code.upper(),
                        "number": number,
                        "lang": lang,
                        "lang_label": lang_label(lang),
                        "foil": e["foil"],
                        "name_en": "",
                        "name_zh": "",
                        "name_printed": "",
                        "type_line": "",
                        "type_line_en": "",
                        "types": [],
                        "mana_cost": "",
                        "cmc": 0,
                        "text": "",
                        "image": {"small": "", "normal": "", "large": ""},
                        "scryfall_uri": "",
                        "image_lang": lang,
                        "error": "not_found",
                        "source_file": e["source_file"],
                    }
                )
                continue

            base = base_from_card(card, client, set_code, number, lang)

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
                "set": base["set"],
                "set_name": base["set_name"],
                "number": base["number"],
                "lang": e["lang"],
                "lang_label": lang_label(e["lang"]),
                "foil": e["foil"],
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
                "image_lang": base.get("image_lang") or e["lang"],
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
        prev = load_previous_enrichment(OUT_JSON, list_key="wants")
        client = ScryfallClient(use_disk_cache=not args.no_cache)
        wants = enrich_wants(entries, client, prev)
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

    # 静态资源 cache buster（独立运行 build_wants 时也能刷新 app.js/style.css）
    for static_file in ("app.js", "style.css"):
        p = ROOT / "assets" / static_file
        if p.exists():
            bump_cache_buster(ROOT / "index.html", static_file, p.read_bytes())

    # 先写前端内嵌 JS（即使 JSON 无变化也写，防 JS 被误删后不重建）
    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    js_bytes = f"window.__MTG_WANTS__={compact};\n".encode()
    OUT_JS.write_bytes(js_bytes)
    # cache buster 基于剔除 generated_at 的稳定内容，避免每小时时间戳变化导致 ?v= 抖动
    bump_cache_buster(ROOT / "index.html", "wants-data.js", stable_payload_bytes(payload, "window.__MTG_WANTS__"))

    if payload_unchanged(OUT_JSON, payload):
        print(f"数据无变化，跳过写入 {OUT_JSON}")
        return 0
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {OUT_JSON} 与 {OUT_JS} （{payload['count']} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
