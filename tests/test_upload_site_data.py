"""upload_site_data staging + promote helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import upload_site_data as usd  # noqa: E402


def test_staging_object_path() -> None:
    assert usd.staging_object_path("cards.json") == "cards.json.next"
    assert usd.staging_object_path("wants.json") == "wants.json.next"


def test_upload_plan_requires_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(usd, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="missing"):
        usd.upload_plan((("data/cards.json", "cards.json", "application/json"),))


def test_upload_snapshots_stages_then_promotes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cards = tmp_path / "cards.json"
    wants = tmp_path / "wants.json"
    cards.write_text("{}", encoding="utf-8")
    wants.write_text("{}", encoding="utf-8")
    plan = [
        (cards, "cards.json", "application/json"),
        (wants, "wants.json", "application/json"),
    ]
    seen: list[str] = []

    def fake_upload(url, key, local, object_path, content_type, *, dry_run=False):
        seen.append(object_path)

    monkeypatch.setattr(usd, "upload_one", fake_upload)
    usd.upload_snapshots("https://example.supabase.co", "key", plan)
    assert seen == [
        "cards.json.next",
        "wants.json.next",
        "cards.json",
        "wants.json",
    ]


def test_upload_snapshots_dry_run_still_orders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cards = tmp_path / "cards.json"
    cards.write_text("{}", encoding="utf-8")
    plan = [(cards, "cards.json", "application/json")]
    seen: list[tuple[str, bool]] = []

    def fake_upload(url, key, local, object_path, content_type, *, dry_run=False):
        seen.append((object_path, dry_run))

    monkeypatch.setattr(usd, "upload_one", fake_upload)
    usd.upload_snapshots("https://example.supabase.co", "", plan, dry_run=True)
    assert seen == [("cards.json.next", True), ("cards.json", True)]
