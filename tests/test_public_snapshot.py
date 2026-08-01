"""Public snapshot boundaries and runtime configuration."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_common  # noqa: E402


def test_public_snapshot_removes_internal_fields_without_mutating_source() -> None:
    internal = {
        "generated_at": "2026-08-02T00:00:00Z",
        "cards": [
            {
                "id": "card-1",
                "name_en": "Test Card",
                "source_file": "00000000-0000-4000-8000-000000000000.txt",
                "image_cdn_attempted": "scryfall",
                "zhs_art_attempted": True,
                "zh_name_attempted": True,
            }
        ],
    }

    public = build_common.public_snapshot_payload(internal, "cards")

    assert public["cards"] == [{"id": "card-1", "name_en": "Test Card"}]
    assert internal["cards"][0]["source_file"].endswith(".txt")


def test_public_snapshot_requires_list() -> None:
    with pytest.raises(ValueError):
        build_common.public_snapshot_payload({"cards": {}}, "cards")
    with pytest.raises(ValueError):
        build_common.public_snapshot_payload({"cards": [{"id": "x"}, "bad"]}, "cards")


def test_write_enrichment_cache_keeps_private_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(build_common, "ENRICHMENT_CACHE_DIR", tmp_path)
    payload = {"cards": [{"id": "x", "source_file": "private.txt"}]}

    path = build_common.write_enrichment_cache(payload, "cards")

    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_site_config_js_matches_loaded_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "site-config.js"
    config = {"title": "Test", "supabase_url": "https://example.supabase.co"}
    monkeypatch.setattr(build_common, "SITE_CONFIG_JS", target)
    monkeypatch.setattr(build_common, "load_site_config", lambda: config)

    content = build_common.write_site_config_js()

    assert content == b'window.__MTG_SITE__={"title":"Test","supabase_url":"https://example.supabase.co"};\n'
    assert target.read_bytes() == content


def test_tracked_site_config_js_matches_repository_config() -> None:
    prefix = "window.__MTG_SITE__="
    raw = (ROOT / "assets" / "site-config.js").read_text(encoding="utf-8").strip()
    assert raw.startswith(prefix) and raw.endswith(";")
    tracked = json.loads(raw[len(prefix) : -1])
    assert tracked == build_common.load_site_config()


@pytest.mark.parametrize("html_path", [ROOT / "index.html", ROOT / "admin" / "index.html"])
def test_html_does_not_eagerly_load_catalog_fallbacks(html_path: Path) -> None:
    html = html_path.read_text(encoding="utf-8")
    assert 'src="assets/cards-data.js' not in html
    assert 'src="/assets/cards-data.js' not in html
    assert 'src="assets/wants-data.js' not in html
    assert 'src="/assets/wants-data.js' not in html
    assert "site-config.js" in html
