#!/usr/bin/env python3
"""Restore app tables from a logical backup produced by backup_supabase.py.

WARNING: This overwrites rows by primary key (upsert). It does not recreate
Auth users with passwords — re-invite or set passwords manually after
importing profiles.

Usage
  # From unpacked directory
  SUPABASE_SERVICE_ROLE_KEY=... python3 scripts/restore_supabase_backup.py backups/supabase-20260101T000000Z

  # From tarball
  SUPABASE_SERVICE_ROLE_KEY=... python3 scripts/restore_supabase_backup.py backups/supabase-20260101T000000Z.tar.gz

  # Dry-run (print counts only)
  SUPABASE_SERVICE_ROLE_KEY=... python3 scripts/restore_supabase_backup.py path --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_common import load_supabase_url  # noqa: E402

REQUEST_TIMEOUT = 60
# Order: profiles first (FKs from inventory/wants)
TABLES = ("profiles", "inventory", "wants")
BATCH = 200


def _key() -> str:
    k = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not k:
        sys.exit("FATAL: SUPABASE_SERVICE_ROLE_KEY not set")
    return k


def unpack_if_needed(path: Path) -> Path:
    if path.is_dir():
        return path
    if not path.is_file() or not path.name.endswith(".tar.gz"):
        sys.exit(f"FATAL: need a backup dir or .tar.gz, got {path}")
    tmp = Path(tempfile.mkdtemp(prefix="mtg-restore-"))
    with tarfile.open(path, "r:gz") as tar:
        tar.extractall(tmp)
    # expect single top-level dir
    kids = [p for p in tmp.iterdir() if p.is_dir()]
    if len(kids) == 1:
        return kids[0]
    return tmp


def load_rows(backup_dir: Path, table: str) -> list[dict[str, Any]]:
    p = backup_dir / f"{table}.json"
    if not p.is_file():
        print(f"⚠ missing {p.name}, skip")
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        sys.exit(f"FATAL: {p} is not a JSON array")
    return data


def upsert_table(
    supabase_url: str,
    key: str,
    table: str,
    rows: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> None:
    if not rows:
        print(f"{table}: 0 rows")
        return
    if dry_run:
        print(f"{table}: would upsert {len(rows)} rows")
        return
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    url = f"{supabase_url.rstrip('/')}/rest/v1/{table}"
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        r = requests.post(url, headers=headers, json=batch, timeout=REQUEST_TIMEOUT)
        if r.status_code not in (200, 201, 204):
            sys.exit(
                f"FATAL: upsert {table} batch {i // BATCH} HTTP {r.status_code}: {r.text[:500]}"
            )
        print(f"{table}: upserted {i + len(batch)}/{len(rows)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Restore mtg-showcase logical backup")
    ap.add_argument("path", type=Path, help="backup directory or .tar.gz")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--skip-auth-note",
        action="store_true",
        help="Suppress reminder about Auth user recreation",
    )
    args = ap.parse_args()

    backup_dir = unpack_if_needed(args.path.resolve())
    manifest_path = backup_dir / "manifest.json"
    if manifest_path.is_file():
        print("manifest:", manifest_path.read_text(encoding="utf-8")[:400])

    key = _key()
    url = load_supabase_url()
    for table in TABLES:
        rows = load_rows(backup_dir, table)
        upsert_table(url, key, table, rows, dry_run=args.dry_run)

    auth_path = backup_dir / "auth_users.json"
    if auth_path.is_file() and not args.skip_auth_note:
        n = len(json.loads(auth_path.read_text(encoding="utf-8")))
        print(
            f"\nNOTE: {n} auth users listed in backup. This script does NOT recreate "
            "Auth accounts/passwords. Re-invite users or restore Auth via Supabase "
            "support/Pro backup if needed; then re-link profiles by id."
        )
    print("done" + (" (dry-run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
