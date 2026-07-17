#!/usr/bin/env python3
"""Supabase -> wants/*.txt（替代 fetch_wps_share + parse_wps_wants_excel）。

读 profiles + wants（含 must/price/note），按 buyer 写 wants/{uid}.txt，
自动补 # seller/city/contact 头（buyer 共用 profiles）。行格式：
set number lang foil qty must price # note（见 SUPABASE_MIGRATION_PLAN.md 第 5/6 节）。

env: SUPABASE_SERVICE_ROLE_KEY。失败 exit 非零。
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_common import fetch_all, load_supabase_url, profile_complete, write_txt  # noqa: E402
from inventory_format import LANG_TOKEN  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WANTS_DIR = ROOT / "wants"

PROFILE_SELECT = "id,seller_name,city,contact"  # buyer 共用 profiles，昵称字段仍是 seller_name
WANTS_SELECT = "buyer_id,set_code,number,lang,foil,quantity,must,price,note"


def format_want_line(row: dict[str, Any]) -> str:
    """wants 行 -> txt 行：set number lang foil qty must price [# note]。"""
    tok = LANG_TOKEN.get(row["lang"], "e")
    foil_s = "1" if row["foil"] else "0"
    must_s = "1" if row["must"] else "0"
    price = float(row["price"])
    line = (
        f"{row['set_code']} {row['number']} {tok} {foil_s} "
        f"{row['quantity']} {must_s} {price:.2f}"
    )
    note = (row.get("note") or "").strip()
    if note:
        line += f" # {note}"
    return line


def main() -> int:
    url = load_supabase_url()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        print("FATAL: SUPABASE_SERVICE_ROLE_KEY 未设置", file=sys.stderr)
        return 1

    try:
        profiles = fetch_all(url, key, "profiles", PROFILE_SELECT)
        wants = fetch_all(url, key, "wants", WANTS_SELECT)
    except Exception as e:
        print(f"FATAL: Supabase 请求失败: {e}", file=sys.stderr)
        return 1

    by_buyer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in wants:
        by_buyer[row["buyer_id"]].append(row)

    if WANTS_DIR.is_dir():
        for p in WANTS_DIR.glob("*.txt"):
            p.unlink()

    written = 0
    skipped: list[str] = []
    for prof in profiles:
        pid = prof["id"]
        rows = by_buyer.get(pid)
        if not rows:
            continue
        if not profile_complete(prof):
            skipped.append(prof.get("seller_name") or pid)
            continue
        # name_field=seller_name：buyer 昵称也存 seller_name 列（profiles 共用）；role=buyer 写 `# buyer:` 头
        write_txt(WANTS_DIR, pid, prof, rows, format_want_line, role="buyer")
        written += 1
        print(f"  · wants/{pid}.txt: {len(rows)} 行（{prof.get('seller_name')}）")

    if written == 0:
        if not by_buyer:
            # wants 为空不算 fatal：站点求购区显示空（build_wants 有空数据保护）
            print("⚠ 无求购数据，写空 wants（站点求购区为空）", file=sys.stderr)
            WANTS_DIR.mkdir(parents=True, exist_ok=True)
            return 0
        print(
            f"FATAL: {len(by_buyer)} buyers found, 0 exported "
            f"(all skipped due to incomplete profile): {', '.join(skipped)}",
            file=sys.stderr,
        )
        return 1

    if skipped:
        print(
            f"[warn] 跳过 {len(skipped)} 个 profile 不全的买家: {', '.join(skipped)}",
            file=sys.stderr,
        )
    print(f"✅ 导出 {written} 个买家 -> wants/*.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
