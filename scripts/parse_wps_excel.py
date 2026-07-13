#!/usr/bin/env python3
"""解析 WPS 库存协作 Excel -> inventory/*.txt（供 build_data 使用）。

约定（与 templates/WPS库存协作模板.xlsx 一致）：
  - 跳过工作表：说明、模板、名称以「模板」开头
  - 昵称/城市/联系：A4/A5/A6 标签，B 列值（或前几行「昵称」键值）
  - 卡表：表头行含「系列」「编号」，其下为数据
  - 语言：e=英 z=中 j=日 o=其他（空默认 e）
  - 闪：空/0=否 1=是
  - 数量：空=1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inventory_format import (  # noqa: E402
    LANG_TOKEN,
    ParseError,
    cell_str,
    merge_cards,
    normalize_foil,
    normalize_lang,
    normalize_qty,
    validate_meta,
)
from wps_excel_common import (  # noqa: E402
    find_header_row,
    find_meta,
    parse_workbook,
    write_sheets,
)

ROOT = Path(__file__).resolve().parents[1]

# 昵称/城市/联系 标签 -> meta key
KEY_MAP = {
    "昵称": "seller",
    "卖家昵称": "seller",
    "卖家": "seller",
    "seller": "seller",
    "城市": "city",
    "city": "city",
    "联系": "contact",
    "联系方式": "contact",
    "contact": "contact",
    "微信": "contact",
}
# 表头标签 -> 字段（库存无 must 列）
HEADER_ALIASES = {
    "系列": "set",
    "系列缩写": "set",
    "set": "set",
    "编号": "number",
    "收集编号": "number",
    "number": "number",
    "语言": "lang",
    "lang": "lang",
    "闪": "foil",
    "是否闪卡": "foil",
    "闪卡": "foil",
    "foil": "foil",
    "数量": "qty",
    "qty": "qty",
    "数量*": "qty",
    "备注": "note",
    "备注（可选）": "note",
    "note": "note",
}
META_KEYS = ("seller", "city", "contact")


def parse_sheet(ws, sheet_name: str) -> tuple[dict[str, str], list[dict[str, Any]], list[str]]:
    """返回 (meta, cards, errors)。"""
    errors: list[str] = []
    meta = find_meta(ws, KEY_MAP, META_KEYS)
    header = find_header_row(ws, HEADER_ALIASES)
    if not header:
        errors.append(f"[{sheet_name}] 未找到表头（需要「系列」「编号」列）")
        return meta, [], errors

    header_row, colmap = header
    cards: list[dict[str, Any]] = []

    for r_idx, row in enumerate(
        ws.iter_rows(min_row=header_row + 1, max_col=12, values_only=True),
        header_row + 1,
    ):
        if not row or all(cell_str(c) == "" for c in row):
            continue
        try:
            set_code = cell_str(row[colmap["set"]]).lower()
            number = cell_str(row[colmap["number"]])
            if not set_code and not number:
                continue
            if not set_code or not number:
                raise ParseError("系列与编号须同时填写", r_idx)

            lang = normalize_lang(row[colmap["lang"]] if "lang" in colmap else "")
            foil = normalize_foil(row[colmap["foil"]] if "foil" in colmap else "")
            qty = normalize_qty(row[colmap["qty"]] if "qty" in colmap else "")

            cards.append(
                {
                    "set": set_code,
                    "number": number,
                    "lang": lang,
                    "foil": foil,
                    "quantity": qty,
                    "line": r_idx,
                }
            )
        except ParseError as e:
            errors.append(f"[{sheet_name}] 第{r_idx}行：{e}")

    errors.extend(validate_meta(meta, sheet_name))
    return meta, cards, errors


def cards_to_txt(meta: dict[str, str], cards: list[dict[str, Any]]) -> str:
    lines = [
        f"# seller: {meta.get('seller') or ''}",
        f"# city: {meta.get('city') or ''}",
        f"# contact: {meta.get('contact') or ''}",
        "#",
        "# 由 parse_wps_excel.py 生成 - 语言 e/z/j/o（空默认e） 闪 0/1  数量默认1",
        "",
    ]
    for c in cards:
        # 内部 txt：与 build_data 兼容
        # lang: en->e, zhs->z, ja->j, other->o
        lang_token = LANG_TOKEN.get(c["lang"], "e")
        foil_token = "1" if c["foil"] else "0"
        qty = c["quantity"]
        prefix = f"{qty}x " if qty != 1 else ""
        lines.append(f"{prefix}{c['set']} {c['number']} {lang_token} {foil_token}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="WPS Excel -> inventory/*.txt")
    parser.add_argument("xlsx", type=Path, help="WPS 导出的 xlsx 路径")
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=ROOT / "inventory",
        help="输出 inventory 目录（默认 ./inventory）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验并打印摘要，不写文件",
    )
    args = parser.parse_args()

    if not args.xlsx.is_file():
        print(f"文件不存在: {args.xlsx}", file=sys.stderr)
        return 1

    print(f"解析 {args.xlsx} …")
    sheets, errors = parse_workbook(args.xlsx, parse_sheet, merge_cards)

    if errors:
        print(f"\n❌ 校验失败（{len(errors)} 个问题）：", file=sys.stderr)
        for e in errors:
            print(f"  · {e}", file=sys.stderr)
        return 1

    if not sheets:
        print("没有可导入的工作表（是否只有「说明/模板」？）", file=sys.stderr)
        return 1

    print("\n✅ 校验通过：")
    for name, (meta, cards) in sheets.items():
        total = sum(c["quantity"] for c in cards)
        print(
            f"  · {name}: {meta.get('seller')} / {meta.get('city')} "
            f"- {len(cards)} 种 / {total} 张"
        )

    if args.dry_run:
        print("\n(--dry-run，未写入文件)")
        return 0

    write_sheets(sheets, cards_to_txt, "seller", args.out_dir, "seller", ROOT)
    print("\n下一步: python3 scripts/build_data.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
