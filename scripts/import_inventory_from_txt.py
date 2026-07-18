#!/usr/bin/env python3
"""claystan.txt（手写牌表） -> Supabase inventory 全量同步。

与 export_inventory_to_txt.py 反向：把根目录手写牌表（`# seller:` 头 + 位置格式行）
作为唯一权威，对齐该卖家在 DB 的库存行。

同步策略（全量替换）：
- txt 有 DB 无 -> insert
- txt 有 DB 有（同 unique key）且 qty 不同 -> update quantity
- txt 有 DB 有且 qty 相同 -> 不动
- txt 无 DB 有 -> delete

DB unique key = (seller_id, set_code, number, lang, foil, price, note)（见
SUPABASE_MIGRATION_PLAN.md 第 4 节 inventory_uniq）。txt 行未写 price/note 时
默认 0/''，会与 DB 里同卡带 price/note 的行算作不同 key -- 全量替换下后者会被删、
前者按 txt 插入（即覆盖成市价）。如需保留 DB 已有 price/note，勿用本脚本全量模式。

owner 强制 = txt 头 `# seller:` 对应的 profile UID（按 lower(seller_name) 查），
service_role bypass RLS 写入。

env: SUPABASE_SERVICE_ROLE_KEY。默认 --dry-run，加 --apply 才真写。
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_common import fetch_all, load_supabase_url, require_service_role_key  # noqa: E402
from inventory_format import META_RE, ParseError, card_line_to_fields  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE = ROOT / "claystan.txt"

INVENTORY_SELECT = "id,set_code,number,lang,foil,quantity,price,note"
# 与 DB unique index inventory_uniq 完全一致（见 admin.js bulkUpsert / 第 4 节）
ON_CONFLICT = "seller_id,set_code,number,lang,foil,price,note"
DELETE_BATCH = 50  # id=in.(...) URL 长度安全分批


def parse_txt(path: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """读手写牌表：meta 头（# seller: 等）+ 行（card_line_to_fields）。

    返回 (meta, rows)。rows 已按 unique key 聚合 qty（同 key 多行相加，避免撞约束）。
    price 归一化为 float；lang 存内部码（en/zhs/ja/other）。
    """
    if not path.is_file():
        sys.exit(f"FATAL: 牌表不存在: {path}")
    meta: dict[str, str] = {}
    raw: list[tuple[str, str, str, bool, int, float, str]] = []
    bad: list[str] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        m = META_RE.match(s)
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()
            continue
        if s.startswith("#"):
            continue  # 其它注释行
        try:
            set_code, number, lang, foil, qty, price, note = card_line_to_fields(s)
        except ParseError as e:
            bad.append(f"  L{i}: {line}  -> {e}")
            continue
        raw.append((set_code, number, lang, foil, qty, price, note))
    if bad:
        sys.exit("FATAL: 牌表解析出错:\n" + "\n".join(bad))

    # 按 unique key 聚合 qty（同卡同价同备注多行 -> 一条，数量相加）
    agg: dict[tuple[str, str, str, bool, str, str], int] = defaultdict(int)
    for set_code, number, lang, foil, qty, price, note in raw:
        key = (set_code, number, lang, foil, f"{price:.2f}", (note or "").strip())
        agg[key] += qty
    rows = [
        {
            "set_code": k[0],
            "number": k[1],
            "lang": k[2],
            "foil": k[3],
            "quantity": v,
            "price": float(k[4]),
            "note": k[5],
        }
        for k, v in agg.items()
    ]
    return meta, rows


def find_seller_id(url: str, key: str, seller_name: str) -> str:
    """按 lower(seller_name) 查 profile UID（与 profiles_seller_name_uniq 对齐）。"""
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    r = requests.get(
        f"{url}/rest/v1/profiles",
        headers=headers,
        params={"select": "id,seller_name", "seller_name": f"ilike.{seller_name}"},
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        sys.exit(f"FATAL: profiles 里找不到 seller_name≈{seller_name!r}")
    if len(rows) > 1:
        sys.exit(f"FATAL: seller_name≈{seller_name!r} 匹配到 {len(rows)} 个 profile，需精确指定")
    return rows[0]["id"]


def db_key(row: dict[str, Any]) -> tuple[str, str, str, bool, str, str]:
    """DB 行 / txt 行 -> unique key（price 归一 2 位、note strip，与 build 端一致）。"""
    return (
        row["set_code"],
        row["number"],
        row["lang"],
        bool(row["foil"]),
        f"{float(row['price']):.2f}",
        (row.get("note") or "").strip(),
    )


def compute_diff(
    txt_rows: list[dict[str, Any]], db_rows: list[dict[str, Any]]
) -> dict[str, list]:
    """txt vs DB -> {insert, update, delete, unchanged}。update 含新旧 qty。"""
    txt_by_key = {db_key(r): r for r in txt_rows}
    db_by_key = {db_key(r): r for r in db_rows}

    insert = [r for k, r in txt_by_key.items() if k not in db_by_key]
    update = []
    for k, tr in txt_by_key.items():
        dr = db_by_key.get(k)
        if dr and int(dr["quantity"]) != int(tr["quantity"]):
            update.append({"key": k, "id": dr["id"], "qty_old": int(dr["quantity"]), "qty_new": int(tr["quantity"])})
    delete = [dr for k, dr in db_by_key.items() if k not in txt_by_key]
    unchanged = [k for k in txt_by_key if k in db_by_key and int(db_by_key[k]["quantity"]) == int(txt_by_key[k]["quantity"])]
    return {"insert": insert, "update": update, "delete": delete, "unchanged": unchanged}


def _row_label(r: dict[str, Any]) -> str:
    foil_s = "闪" if r["foil"] else "非闪"
    return f"{r['set_code']} {r['number']} {r['lang']} {foil_s} qty={r['quantity']}"


def print_diff(diff: dict[str, list], seller_name: str) -> None:
    ins, upd, dele, keep = diff["insert"], diff["update"], diff["delete"], diff["unchanged"]
    print(f"== {seller_name} 全量同步 dry-run ==")
    print(f"  insert   {len(ins):4d}")
    print(f"  update   {len(upd):4d}  (qty 变更)")
    print(f"  delete   {len(dele):4d}  (txt 没有的卡)")
    print(f"  keep     {len(keep):4d}  (qty 相同，不动)")
    print(f"  txt 合计 {len(ins) + len(upd) + len(keep):4d}  | DB 现有 {len(dele) + len(upd) + len(keep)}")
    if ins:
        print("  -- insert 样例 --")
        for r in ins[:8]:
            print(f"    + {_row_label(r)}")
    if upd:
        print("  -- update 样例 --")
        for u in upd[:8]:
            k = u["key"]
            print(f"    ~ {k[0]} {k[1]} {k[2]} {'闪' if k[3] else '非闪'} qty {u['qty_old']}->{u['qty_new']}")
    if dele:
        print("  -- delete 样例 --")
        for r in dele[:8]:
            k = db_key(r)
            print(f"    - {k[0]} {k[1]} {k[2]} {'闪' if k[3] else '非闪'} qty={r['quantity']} (id {r['id'][:8]})")


def apply_diff(
    url: str, key: str, seller_id: str, txt_rows: list[dict[str, Any]], diff: dict[str, list]
) -> None:
    """执行全量替换：upsert 所有 txt 行（onConflict merge）+ 分批 delete txt 没有的 id。

    upsert 一次原子；delete 按 id 列表分批。中途失败抛异常，已 upsert 的不回滚
    （但 upsert 幂等，重跑安全；delete 失败重跑也安全，因为 diff 基于最新 DB 重算）。
    """
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    # 1) upsert 所有 txt 行（insert 新 + update 已有 qty，按 unique key merge）
    payload = [{**r, "seller_id": seller_id} for r in txt_rows]
    r = requests.post(
        f"{url}/rest/v1/inventory",
        headers=headers,
        params={"on_conflict": ON_CONFLICT},
        json=payload,
        timeout=60,
    )
    if not r.ok:
        sys.exit(f"FATAL: upsert 失败 {r.status_code}: {r.text[:500]}")
    print(f"  ✓ upsert {len(payload)} 行")

    # 2) 分批 delete txt 没有的行（按 id，每批 DELETE_BATCH 个）
    to_delete = [d["id"] for d in diff["delete"]]
    for i in range(0, len(to_delete), DELETE_BATCH):
        batch = to_delete[i : i + DELETE_BATCH]
        ids_param = f"in.({','.join(batch)})"
        r = requests.delete(
            f"{url}/rest/v1/inventory",
            headers={**headers, "Prefer": "return=representation"},
            params={"id": ids_param, "seller_id": f"eq.{seller_id}"},
            timeout=30,
        )
        if not r.ok:
            sys.exit(f"FATAL: delete 失败 {r.status_code}: {r.text[:500]}")
    print(f"  ✓ delete {len(to_delete)} 行")


def main() -> int:
    ap = argparse.ArgumentParser(description="手写牌表 -> Supabase inventory 全量同步")
    ap.add_argument("--file", default=str(DEFAULT_FILE), help="牌表路径（默认 claystan.txt）")
    ap.add_argument("--seller", default=None, help="覆盖 txt 头的 seller 名（查 profile UID）")
    ap.add_argument("--apply", action="store_true", help="真写（默认 dry-run）")
    args = ap.parse_args()

    url = load_supabase_url()
    key = require_service_role_key()

    meta, txt_rows = parse_txt(Path(args.file))
    seller_name = (args.seller or meta.get("seller") or "").strip()
    if not seller_name:
        sys.exit("FATAL: 牌表无 # seller: 头且未传 --seller")

    seller_id = find_seller_id(url, key, seller_name)
    print(f"seller: {seller_name}  uid: {seller_id}")
    print(f"txt 解析: {len(txt_rows)} 行（去重聚合后）")

    db_rows = fetch_all(url, key, "inventory", INVENTORY_SELECT)
    db_rows = [r for r in db_rows if r["seller_id"] == seller_id]
    print(f"DB 现有: {len(db_rows)} 行")

    diff = compute_diff(txt_rows, db_rows)
    print_diff(diff, seller_name)

    if not args.apply:
        print("\n[dry-run] 未写入。确认无误后加 --apply 执行。")
        return 0

    print("\n[apply] 写入中 ...")
    apply_diff(url, key, seller_id, txt_rows, diff)
    print("✅ 同步完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
