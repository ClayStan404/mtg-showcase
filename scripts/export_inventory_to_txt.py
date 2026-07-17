#!/usr/bin/env python3
"""Supabase -> inventory/*.txt（替代 fetch_wps_share + parse_wps_excel）。

读 profiles + inventory（含 price/note），按 seller 写 inventory/{uid}.txt，
自动补 # seller/city/contact 头。行格式：set number lang foil qty price # note
（见 SUPABASE_MIGRATION_PLAN.md 第 5/6 节）。

env: SUPABASE_SERVICE_ROLE_KEY（service_role，bypass RLS 读全部卖家）。
失败（请求失败/0 seller/全 profile 不全）exit 非零，让 workflow step 失败、不部署空站点。
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
INVENTORY_DIR = ROOT / "inventory"

PROFILE_SELECT = "id,seller_name,city,contact"
INVENTORY_SELECT = "seller_id,set_code,number,lang,foil,quantity,price,note"


def format_inventory_line(row: dict[str, Any]) -> str:
    """inventory 行 -> txt 行：set number lang foil qty price [# note]。

    price 一律 `:.2f`（2 位小数，如 50.00），与 build 端 card_id 格式化对齐。
    DB 的 lang 存内部码（en/zhs/ja/other），写 txt 用简写 token（e/z/j/o）。
    """
    tok = LANG_TOKEN.get(row["lang"], "e")
    foil_s = "1" if row["foil"] else "0"
    price = float(row["price"])  # REST 返回 numeric 为字符串，必须 float 后再格式化
    line = f"{row['set_code']} {row['number']} {tok} {foil_s} {row['quantity']} {price:.2f}"
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
        inventory = fetch_all(url, key, "inventory", INVENTORY_SELECT)
    except Exception as e:  # requests.RequestException / 网络超时 / JSON 解析
        print(f"FATAL: Supabase 请求失败: {e}", file=sys.stderr)
        return 1

    by_seller: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in inventory:
        by_seller[row["seller_id"]].append(row)

    # 先清旧产物，避免卖家清空库存后旧 txt 残留展示已下架的卡
    if INVENTORY_DIR.is_dir():
        for p in INVENTORY_DIR.glob("*.txt"):
            p.unlink()

    written = 0
    skipped: list[str] = []
    for prof in profiles:
        pid = prof["id"]
        rows = by_seller.get(pid)
        if not rows:
            continue  # 无库存行，不写文件
        if not profile_complete(prof):
            skipped.append(prof.get("seller_name") or pid)
            continue  # profile 不全 -> build 的 validate_meta 会 SystemExit，整批跳过
        write_txt(INVENTORY_DIR, pid, prof, rows, format_inventory_line)
        written += 1
        print(f"  · inventory/{pid}.txt: {len(rows)} 行（{prof.get('seller_name')}）")

    if written == 0:
        if not by_seller:
            print("FATAL: no sellers found in Supabase", file=sys.stderr)
        else:
            print(
                f"FATAL: {len(by_seller)} sellers found, 0 exported "
                f"(all skipped due to incomplete profile): {', '.join(skipped)}",
                file=sys.stderr,
            )
        return 1

    if skipped:
        print(
            f"[warn] 跳过 {len(skipped)} 个 profile 不全的卖家（库存不展示）: {', '.join(skipped)}",
            file=sys.stderr,
        )
    print(f"✅ 导出 {written} 个卖家 -> inventory/*.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
