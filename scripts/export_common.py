#!/usr/bin/env python3
"""Supabase -> inventory/*.txt + wants/*.txt 导出共享层。

export_inventory_to_txt.py / export_wants_to_txt.py 共用：
- 从 site_config.json 读 supabase_url（公开，不进 secret）
- service_role key 从 env 读（bypass RLS，读全部卖家/买家）
- 分页 REST 拉取
- 自动补 meta 头（# seller/city/contact，从 profiles）
- 写 txt（按 profile UID 命名，build 从 # seller 头读昵称生成 seller_id，不依赖文件名）

txt 行格式见 SUPABASE_MIGRATION_PLAN.md 第 5 节（空格分隔 + # note）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

import requests

ROOT = Path(__file__).resolve().parents[1]
SITE_CONFIG = ROOT / "site_config.json"

PAGE_SIZE = 1000  # Supabase REST 默认上限 1000，分页拉全量
REQUEST_TIMEOUT = 30


def load_supabase_url() -> str:
    """从 site_config.json 读 supabase_url（公开字段）。"""
    try:
        cfg = json.loads(SITE_CONFIG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        sys.exit(f"FATAL: site_config.json 读取失败: {e}")
    url = (cfg.get("supabase_url") or "").strip().rstrip("/")
    if not url:
        sys.exit("FATAL: site_config.json 缺 supabase_url（迁移未完成？见 SUPABASE_MIGRATION_PLAN.md 第 10 节）")
    return url


def fetch_all(url: str, key: str, table: str, select: str) -> list[dict[str, Any]]:
    """service_role 分页拉取整张表（bypass RLS）。请求失败抛 RequestException。"""
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        r = requests.get(
            f"{url}/rest/v1/{table}",
            headers=headers,
            params={"select": select, "limit": PAGE_SIZE, "offset": offset},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def format_meta_header(name: str, city: str, contact: str, role: str = "seller") -> str:
    """生成 txt meta 头。role=seller 写 `# seller:`（inventory），role=buyer 写 `# buyer:`（wants）。
    build 的 META_RE 都接受 buyer|seller|nickname|nick 作为昵称键。"""
    return f"# {role}: {name}\n# city: {city}\n# contact: {contact}\n"


def profile_complete(profile: dict[str, Any]) -> bool:
    """seller_name/city/contact 任一为空即不全 -> build 的 validate_meta 会 SystemExit，须跳过。"""
    return all(
        (profile.get(f) or "").strip() for f in ("seller_name", "city", "contact")
    )


def write_txt(
    out_dir: Path,
    profile_id: str,
    profile: dict[str, Any],
    rows: list[dict[str, Any]],
    line_formatter: Callable[[dict[str, Any]], str],
    name_field: str = "seller_name",
    role: str = "seller",
) -> Path:
    """写单个 {profile_id}.txt：meta 头 + 每行一条记录。返回写入路径。
    role 控制昵称头是 `# seller:`（inventory）还是 `# buyer:`（wants）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{profile_id}.txt"
    name = (profile.get(name_field) or "").strip()
    city = (profile.get("city") or "").strip()
    contact = (profile.get("contact") or "").strip()
    parts = [format_meta_header(name, city, contact, role)]
    parts.extend(line_formatter(row) for row in rows)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path
