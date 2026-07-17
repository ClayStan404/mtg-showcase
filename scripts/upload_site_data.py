#!/usr/bin/env python3
"""Upload built cards.json / wants.json to Supabase Storage (public bucket site-data).

Scheme C: buyers read these snapshots from Storage CDN; sellers still write Postgres.
service_role key from env SUPABASE_SERVICE_ROLE_KEY (GitHub Actions secret).

Usage:
  SUPABASE_SERVICE_ROLE_KEY=... python3 scripts/upload_site_data.py
  python3 scripts/upload_site_data.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_common import load_supabase_url  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BUCKET = "site-data"
# Short cache so list updates show quickly after rebuild; bust query still used by clients.
CACHE_CONTROL = "public, max-age=30, must-revalidate"
REQUEST_TIMEOUT = 60

FILES = (
    ("data/cards.json", "cards.json", "application/json"),
    ("data/wants.json", "wants.json", "application/json"),
)


def public_base_url(supabase_url: str) -> str:
    return f"{supabase_url.rstrip('/')}/storage/v1/object/public/{BUCKET}"


def upload_one(
    supabase_url: str,
    key: str,
    local: Path,
    object_path: str,
    content_type: str,
    *,
    dry_run: bool = False,
) -> None:
    if not local.is_file():
        sys.exit(f"FATAL: missing {local} (run build first)")
    size = local.stat().st_size
    if dry_run:
        print(f"dry-run: would upload {local} ({size} bytes) -> {BUCKET}/{object_path}")
        return
    url = f"{supabase_url.rstrip('/')}/storage/v1/object/{BUCKET}/{object_path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": content_type,
        "x-upsert": "true",
        "cache-control": CACHE_CONTROL,
    }
    with local.open("rb") as f:
        r = requests.post(url, headers=headers, data=f, timeout=REQUEST_TIMEOUT)
    if r.status_code not in (200, 201):
        sys.exit(
            f"FATAL: upload {object_path} failed HTTP {r.status_code}: {r.text[:500]}"
        )
    print(f"uploaded {object_path} ({size} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Upload site data snapshots to Storage")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Check files exist and print targets without uploading",
    )
    args = ap.parse_args()

    import os

    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not args.dry_run and not key:
        sys.exit("FATAL: SUPABASE_SERVICE_ROLE_KEY not set")

    supabase_url = load_supabase_url()
    for rel, object_path, ctype in FILES:
        upload_one(
            supabase_url,
            key,
            ROOT / rel,
            object_path,
            ctype,
            dry_run=args.dry_run,
        )
    print(f"public base: {public_base_url(supabase_url)}")


if __name__ == "__main__":
    main()
