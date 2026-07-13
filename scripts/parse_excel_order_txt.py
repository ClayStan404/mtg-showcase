#!/usr/bin/env python3
"""把「Excel 列顺序」的纯文本库存 → inventory/*.txt（供 build_data 使用）。

输入每行（与 WPS 表列一致，空格/制表符分隔）:
  系列  编号  语言  闪  数量

  - 语言: e=英 z=中 j=日 o=其他（空默认 e）
  - 闪: 空/0=否  1=是
  - 数量: 空=1
  - # 开头为注释；空行忽略

输出 inventory 行格式（给 build_data / card_line_to_fields）:
  [Nx] set number lang foil
  例如: 2x neo 111 z 1

与 parse_wps_excel.py 的区别:
  - 本脚本读「手写/导出的普通 txt」
  - parse_wps_excel.py 读真实 .xlsx 工作簿
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventory_format import (  # noqa: E402
    LANG_TOKEN,
    META_RE,
    ParseError,
    cell_str,
    merge_cards,
    normalize_foil,
    normalize_lang,
    normalize_qty,
    slugify,
    validate_meta,
)

ROOT = Path(__file__).resolve().parents[1]


def parse_excel_order_line(line: str, line_num: int) -> dict[str, Any]:
    """系列 编号 [语言] [闪] [数量] — 位置固定，与 Excel 列对齐。"""
    parts = line.split()
    if len(parts) < 2:
        raise ParseError("至少需要 系列 + 编号", line_num)
    if len(parts) > 5:
        raise ParseError("字段过多，格式: 系列 编号 [语言] [闪] [数量]", line_num)

    set_code = parts[0].lower()
    number = cell_str(parts[1])
    if not set_code or not number:
        raise ParseError("系列与编号须同时填写", line_num)

    lang = normalize_lang(parts[2] if len(parts) > 2 else "")
    foil = normalize_foil(parts[3] if len(parts) > 3 else "")
    qty = normalize_qty(parts[4] if len(parts) > 4 else "")

    return {
        "set": set_code,
        "number": number,
        "lang": lang,
        "foil": foil,
        "quantity": qty,
        "line": line_num,
    }


def parse_file(path: Path) -> tuple[dict[str, str], list[dict[str, Any]], list[str]]:
    meta = {"seller": "", "city": "", "contact": ""}
    cards: list[dict[str, Any]] = []
    errors: list[str] = []

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
                        meta["seller"] = val
                    elif key == "city":
                        meta["city"] = val
                    elif key in ("contact", "wechat"):
                        meta["contact"] = val
                continue
            try:
                cards.append(parse_excel_order_line(line, line_num))
            except ParseError as e:
                errors.append(f"第{line_num}行：{e} — {line}")

    return meta, cards, errors


def cards_to_inventory_txt(meta: dict[str, str], cards: list[dict[str, Any]], source: str) -> str:
    """写成 build_data 可读的 inventory 行（数量在行首 Nx）。"""
    lines = [
        f"# seller: {meta.get('seller') or ''}",
        f"# city: {meta.get('city') or ''}",
        f"# contact: {meta.get('contact') or ''}",
        "#",
        f"# 由 parse_excel_order_txt.py 从 {source} 生成",
        "# 库存格式: [Nx] 系列 编号 语言 闪   （语言 e/z/j/o，闪 0/1）",
        "",
    ]
    lang_token = LANG_TOKEN
    for c in cards:
        lt = lang_token.get(c["lang"], "e")
        ft = "1" if c["foil"] else "0"
        qty = c["quantity"]
        prefix = f"{qty}x " if qty != 1 else ""
        lines.append(f"{prefix}{c['set']} {c['number']} {lt} {ft}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Excel 列顺序的纯文本库存 → inventory/*.txt"
    )
    parser.add_argument(
        "txt",
        type=Path,
        help="输入 txt（每行: 系列 编号 语言 闪 数量）",
    )
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=ROOT / "inventory",
        help="输出目录（默认 ./inventory）",
    )
    parser.add_argument(
        "--name",
        default="",
        help="输出文件名 stem（默认用输入文件名，如 claystan → claystan.txt）",
    )
    parser.add_argument(
        "--seller",
        default="",
        help="覆盖 # seller:（也可用输入文件内 # seller: 行）",
    )
    parser.add_argument("--city", default="", help="覆盖 # city:")
    parser.add_argument("--contact", default="", help="覆盖 # contact:")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验并打印摘要，不写文件",
    )
    args = parser.parse_args()

    if not args.txt.is_file():
        print(f"文件不存在: {args.txt}", file=sys.stderr)
        return 1

    print(f"解析 {args.txt} …")
    meta, cards, errors = parse_file(args.txt)

    if args.seller:
        meta["seller"] = args.seller
    if args.city:
        meta["city"] = args.city
    if args.contact:
        meta["contact"] = args.contact

    errors.extend(validate_meta(meta, args.txt.name))

    if errors:
        print(f"\n❌ 校验失败（{len(errors)} 个问题）：", file=sys.stderr)
        for e in errors:
            print(f"  · {e}", file=sys.stderr)
        return 1

    cards = merge_cards(cards)
    total = sum(c["quantity"] for c in cards)
    print(
        f"✅ {meta.get('seller')} / {meta.get('city') or '—'} "
        f"— {len(cards)} 种 / {total} 张"
    )

    if args.dry_run:
        for c in cards[:15]:
            print(
                f"  · {c['set']} {c['number']} {c['lang']} "
                f"{'foil' if c['foil'] else 'nf'} ×{c['quantity']}"
            )
        if len(cards) > 15:
            print(f"  … 另有 {len(cards) - 15} 种")
        print("\n(--dry-run，未写入文件)")
        return 0

    stem = (args.name or args.txt.stem).strip() or "inventory"
    # 安全文件名
    stem = slugify(stem, "inventory")
    out_path = args.out_dir / f"{stem}.txt"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    text = cards_to_inventory_txt(meta, cards, args.txt.name)
    out_path.write_text(text, encoding="utf-8")
    print(f"已写入 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
