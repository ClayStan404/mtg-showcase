"""Unit tests for backup/restore pure helpers (no network)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backup_supabase import (  # noqa: E402
    auth_users_page_batch,
    local_archives_newest_first,
    prune_local,
    remote_archives_newest_first,
    slim_auth_user,
)


def test_auth_users_page_batch_dict_shape() -> None:
    batch = auth_users_page_batch(
        {"users": [{"id": "a", "email": "a@x"}, {"id": "b"}], "aud": "authenticated"}
    )
    assert batch is not None
    assert [u["id"] for u in batch] == ["a", "b"]


def test_auth_users_page_batch_list_shape() -> None:
    batch = auth_users_page_batch([{"id": "1"}, {"id": "2"}])
    assert batch is not None
    assert len(batch) == 2


def test_auth_users_page_batch_empty() -> None:
    assert auth_users_page_batch({"users": []}) == []
    assert auth_users_page_batch([]) == []
    assert auth_users_page_batch({"users": None}) == []


def test_auth_users_page_batch_skips_non_dict_entries() -> None:
    batch = auth_users_page_batch({"users": [{"id": "ok"}, "bad", 3, None]})
    assert batch == [{"id": "ok"}]


def test_auth_users_page_batch_unexpected() -> None:
    assert auth_users_page_batch("nope") is None
    assert auth_users_page_batch(42) is None
    assert auth_users_page_batch({"users": "x"}) is None


def test_slim_auth_user_drops_noise() -> None:
    slim = slim_auth_user(
        {
            "id": "u1",
            "email": "e@x",
            "encrypted_password": "secret",
            "identities": [{"provider": "email"}],
            "app_metadata": {"provider": "email"},
            "user_metadata": {"name": "n"},
        }
    )
    assert slim["id"] == "u1"
    assert slim["email"] == "e@x"
    assert "encrypted_password" not in slim
    assert "identities" not in slim
    assert slim["app_metadata"] == {"provider": "email"}
    assert slim["user_metadata"] == {"name": "n"}


def test_local_archives_newest_first(tmp_path: Path) -> None:
    older = tmp_path / "supabase-20260101T000000Z.tar.gz"
    newer = tmp_path / "supabase-20260102T000000Z.tar.gz"
    older.write_bytes(b"a")
    time.sleep(0.02)
    newer.write_bytes(b"b")
    ordered = local_archives_newest_first([older, newer])
    assert ordered[0] == newer
    assert ordered[1] == older


def test_remote_archives_newest_first_sort_and_filter() -> None:
    objs = [
        {"name": "notes.txt", "updated_at": "2026-07-10T00:00:00Z"},
        {"name": "supabase-old.tar.gz", "updated_at": "2026-07-01T00:00:00Z"},
        {"name": "supabase-mid.tar.gz", "created_at": "2026-07-05T00:00:00Z"},
        {"name": "supabase-new.tar.gz", "updated_at": "2026-07-10T12:00:00Z"},
        "not-a-dict",
        {"name": "supabase-no-ts.tar.gz"},
    ]
    files = remote_archives_newest_first(objs)
    names = [f["name"] for f in files]
    assert names[0] == "supabase-new.tar.gz"
    assert "notes.txt" not in names
    assert "supabase-old.tar.gz" in names
    assert names.index("supabase-mid.tar.gz") < names.index("supabase-old.tar.gz")
    # missing timestamps sort oldest → last among kept list
    assert names[-1] == "supabase-no-ts.tar.gz"


def test_prune_local_keeps_newest(tmp_path: Path) -> None:
    names = [
        "supabase-20260101T000000Z.tar.gz",
        "supabase-20260102T000000Z.tar.gz",
        "supabase-20260103T000000Z.tar.gz",
    ]
    for i, name in enumerate(names):
        p = tmp_path / name
        p.write_bytes(b"x")
        # ensure mtime order matches name order (oldest first)
        ts = time.time() - (len(names) - i) * 10
        os.utime(p, (ts, ts))

    # also create unpacked dir for the oldest archive
    unpacked = tmp_path / "supabase-20260101T000000Z"
    unpacked.mkdir()
    (unpacked / "manifest.json").write_text("{}", encoding="utf-8")

    prune_local(keep=2, backup_root=tmp_path)

    remaining = sorted(p.name for p in tmp_path.glob("supabase-*.tar.gz"))
    assert remaining == [
        "supabase-20260102T000000Z.tar.gz",
        "supabase-20260103T000000Z.tar.gz",
    ]
    assert not unpacked.exists()


def test_prune_local_keep_zero_noop(tmp_path: Path) -> None:
    p = tmp_path / "supabase-20260101T000000Z.tar.gz"
    p.write_bytes(b"x")
    prune_local(keep=0, backup_root=tmp_path)
    assert p.is_file()


def test_prune_local_keep_all(tmp_path: Path) -> None:
    for name in (
        "supabase-a.tar.gz",
        "supabase-b.tar.gz",
    ):
        (tmp_path / name).write_bytes(b"x")
    prune_local(keep=5, backup_root=tmp_path)
    assert len(list(tmp_path.glob("*.tar.gz"))) == 2
