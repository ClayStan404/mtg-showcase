#!/usr/bin/env python3
"""Logical backup of Supabase app data (Free-tier friendly).

Does NOT replace Pro plan daily backups / PITR. This dumps business tables
via PostgREST with service_role (bypass RLS), optionally lists Auth users,
and writes a timestamped archive. Optional upload to a **private** Storage
bucket (`db-backups`) so off-machine copies exist.

What is included
  - public.profiles, public.inventory, public.wants (full rows)
  - auth users list via Auth Admin API (id/email/created_at/…; no passwords)

What is NOT included
  - Full Postgres physical backup / roles / extensions
  - Storage objects other than what you upload here
  - Secrets / JWT private keys

Consistency note
  Tables are fetched sequentially with offset pagination (same as export).
  Concurrent writes during the dump can yield a cross-table snapshot that is
  not perfectly FK-consistent (e.g. inventory row for a profile created mid-
  backup). At our scale the window is short; acceptable for logical recovery.
  True transactional snapshots would need Postgres-level tools (pg_dump /
  Pro PITR), not REST.

Usage
  SUPABASE_SERVICE_ROLE_KEY=... python3 scripts/backup_supabase.py
  SUPABASE_SERVICE_ROLE_KEY=... python3 scripts/backup_supabase.py --no-upload
  SUPABASE_SERVICE_ROLE_KEY=... python3 scripts/backup_supabase.py --keep-local 7 --keep-remote 30

Restore (ops): see scripts/restore_supabase_backup.py
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_common import fetch_all, load_supabase_url, require_service_role_key  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BACKUP_ROOT = ROOT / "backups"
BUCKET = "db-backups"
REQUEST_TIMEOUT = 60

# Core app tables (expand if schema grows)
TABLES: list[tuple[str, str]] = [
    ("profiles", "*"),
    ("inventory", "*"),
    ("wants", "*"),
]


def auth_users_page_batch(data: Any) -> list[dict[str, Any]] | None:
    """Normalize one Auth Admin API page body to a list of user dicts.

    Returns:
      - list of dicts (possibly empty) when payload is understood
      - None when the payload shape is unexpected (caller should stop)
    """
    batch = data.get("users") if isinstance(data, dict) else data
    if batch is None:
        return []
    if not isinstance(batch, list):
        return None
    out: list[dict[str, Any]] = []
    for u in batch:
        if isinstance(u, dict):
            out.append(u)
    return out


def slim_auth_user(u: dict[str, Any]) -> dict[str, Any]:
    """Keep inventory-restore-relevant fields only (no passwords / tokens)."""
    return {
        "id": u.get("id"),
        "email": u.get("email"),
        "phone": u.get("phone"),
        "created_at": u.get("created_at"),
        "updated_at": u.get("updated_at"),
        "last_sign_in_at": u.get("last_sign_in_at"),
        "email_confirmed_at": u.get("email_confirmed_at"),
        "banned_until": u.get("banned_until"),
        "role": u.get("role"),
        "app_metadata": u.get("app_metadata") or {},
        # user_metadata is user-editable; kept for nickname recovery only
        "user_metadata": u.get("user_metadata") or {},
    }


def fetch_auth_users(supabase_url: str, key: str) -> list[dict[str, Any]]:
    """List users via Auth Admin API (service_role). Paginated."""
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    users: list[dict[str, Any]] = []
    page = 1
    per_page = 200
    while True:
        r = requests.get(
            f"{supabase_url.rstrip('/')}/auth/v1/admin/users",
            headers=headers,
            params={"page": page, "per_page": per_page},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 404:
            print("⚠ Auth Admin users endpoint 404 — skip auth_users")
            return []
        r.raise_for_status()
        batch = auth_users_page_batch(r.json())
        if batch is None:
            print("⚠ unexpected auth users payload type")
            break
        if not batch:
            break
        users.extend(slim_auth_user(u) for u in batch)
        if len(batch) < per_page:
            break
        page += 1
        if page > 100:
            print("⚠ auth users page cap 100 reached")
            break
    return users


def write_json(path: Path, obj: Any) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def make_tarball(src_dir: Path, dest_gz: Path) -> None:
    dest_gz.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest_gz, "w:gz") as tar:
        tar.add(src_dir, arcname=src_dir.name)


def upload_file(
    supabase_url: str, key: str, local: Path, object_path: str
) -> None:
    url = f"{supabase_url.rstrip('/')}/storage/v1/object/{BUCKET}/{object_path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/gzip",
        "x-upsert": "true",
        "cache-control": "private, max-age=0, no-store",
    }
    with local.open("rb") as f:
        r = requests.post(url, headers=headers, data=f, timeout=REQUEST_TIMEOUT)
    if r.status_code not in (200, 201):
        sys.exit(
            f"FATAL: upload {object_path} failed HTTP {r.status_code}: {r.text[:500]}"
        )
    print(f"uploaded gs://{BUCKET}/{object_path} ({local.stat().st_size} bytes)")


def list_remote_objects(supabase_url: str, key: str, prefix: str = "") -> list[dict[str, Any]]:
    """List objects in private bucket (service_role)."""
    url = f"{supabase_url.rstrip('/')}/storage/v1/object/list/{BUCKET}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    r = requests.post(
        url,
        headers=headers,
        json={"prefix": prefix, "limit": 1000, "offset": 0},
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code != 200:
        print(f"⚠ list remote backups failed HTTP {r.status_code}: {r.text[:200]}")
        return []
    data = r.json()
    return data if isinstance(data, list) else []


def delete_remote(supabase_url: str, key: str, object_path: str) -> None:
    url = f"{supabase_url.rstrip('/')}/storage/v1/object/{BUCKET}/{object_path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    r = requests.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
    if r.status_code not in (200, 204):
        print(f"⚠ delete {object_path} HTTP {r.status_code}: {r.text[:200]}")
    else:
        print(f"deleted remote {object_path}")


def local_archives_newest_first(paths: list[Path]) -> list[Path]:
    """Sort local backup archives newest-first by mtime (then name)."""
    return sorted(
        paths,
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )


def remote_archives_newest_first(objs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter .tar.gz Storage objects and sort newest-first.

    Prefer updated_at, then created_at. Missing timestamps sort as oldest so
    undated objects are pruned first (do not use `name` as a time proxy —
    lexicographic names can outrank real ISO timestamps).
    """
    files = [
        o
        for o in objs
        if isinstance(o, dict) and str(o.get("name") or "").endswith(".tar.gz")
    ]
    files.sort(
        key=lambda o: str(o.get("updated_at") or o.get("created_at") or ""),
        reverse=True,
    )
    return files


def prune_local(keep: int, backup_root: Path | None = None) -> None:
    if keep <= 0:
        return
    root = backup_root if backup_root is not None else BACKUP_ROOT
    archives = local_archives_newest_first(list(root.glob("supabase-*.tar.gz")))
    for old in archives[keep:]:
        old.unlink(missing_ok=True)
        # remove matching unpacked dir if present
        d = root / old.name.replace(".tar.gz", "")
        if d.is_dir():
            for f in d.iterdir():
                f.unlink(missing_ok=True)
            d.rmdir()
        print(f"pruned local {old.name}")


def prune_remote(supabase_url: str, key: str, keep: int) -> None:
    if keep <= 0:
        return
    objs = list_remote_objects(supabase_url, key, prefix="")
    files = remote_archives_newest_first(objs)
    for o in files[keep:]:
        name = str(o.get("name") or "")
        if name:
            delete_remote(supabase_url, key, name)


def run_backup(
    *,
    upload: bool,
    keep_local: int,
    keep_remote: int,
    keep_unpacked: bool,
) -> Path:
    key = require_service_role_key()
    url = load_supabase_url()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = BACKUP_ROOT / f"supabase-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    tables_meta: dict[str, int] = {}
    for table, select in TABLES:
        print(f"fetching {table} …")
        rows = fetch_all(url, key, table, select)
        write_json(out_dir / f"{table}.json", rows)
        tables_meta[table] = len(rows)
        print(f"  {table}: {len(rows)} rows")

    print("fetching auth users …")
    auth_users = fetch_auth_users(url, key)
    write_json(out_dir / "auth_users.json", auth_users)
    print(f"  auth_users: {len(auth_users)}")

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "supabase_url": url,
        "tables": tables_meta,
        "auth_users": len(auth_users),
        "format": "mtg-showcase-logical-v1",
        "note": "Logical JSON dump via service_role; not a full pg_dump.",
    }
    write_json(out_dir / "manifest.json", manifest)

    tarball = BACKUP_ROOT / f"supabase-{ts}.tar.gz"
    make_tarball(out_dir, tarball)
    print(f"archive: {tarball} ({tarball.stat().st_size} bytes)")

    if not keep_unpacked:
        for f in out_dir.iterdir():
            f.unlink()
        out_dir.rmdir()
        print("removed unpacked dir (kept .tar.gz only)")

    if upload:
        object_path = tarball.name
        upload_file(url, key, tarball, object_path)
        prune_remote(url, key, keep_remote)

    prune_local(keep_local)
    return tarball


def main() -> None:
    ap = argparse.ArgumentParser(description="Logical Supabase backup for mtg-showcase")
    ap.add_argument(
        "--no-upload",
        action="store_true",
        help="Only write local backups/ (default: also upload to private Storage)",
    )
    ap.add_argument(
        "--keep-local",
        type=int,
        default=14,
        help="Local .tar.gz files to keep (default 14)",
    )
    ap.add_argument(
        "--keep-remote",
        type=int,
        default=30,
        help="Remote Storage objects to keep (default 30)",
    )
    ap.add_argument(
        "--keep-unpacked",
        action="store_true",
        help="Keep backups/supabase-TIMESTAMP/ directory after packing",
    )
    args = ap.parse_args()
    t0 = time.monotonic()
    path = run_backup(
        upload=not args.no_upload,
        keep_local=args.keep_local,
        keep_remote=args.keep_remote,
        keep_unpacked=args.keep_unpacked,
    )
    print(f"done in {time.monotonic() - t0:.1f}s → {path}")


if __name__ == "__main__":
    main()
