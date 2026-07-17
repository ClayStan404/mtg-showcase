"""build_common 纯函数与缓存工具测试。

覆盖 payload_unchanged / bump_cache_buster / load_previous_enrichment /
load_site_config / pick_* / classify_types / base_from_* 的边界情况，
重点保护影响部署正确性的增量缓存与 cache buster 逻辑。
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_common  # noqa: E402


# ── data_base_url / scheme C ─────────────────────────────────────────
def test_data_base_url_from_supabase():
    assert (
        build_common.data_base_url_from_supabase(
            "https://abc.supabase.co", "site-data"
        )
        == "https://abc.supabase.co/storage/v1/object/public/site-data"
    )
    assert build_common.data_base_url_from_supabase("") == ""
    assert build_common.data_base_url_from_supabase("https://x.supabase.co/") == (
        "https://x.supabase.co/storage/v1/object/public/site-data"
    )


def test_load_site_config_derives_data_base_url(tmp_path, monkeypatch):
    cfg_path = tmp_path / "site_config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "title": "T",
                "subtitle": "S",
                "supabase_url": "https://proj.supabase.co",
                "supabase_anon_key": "anon",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(build_common, "SITE_CONFIG", cfg_path)
    cfg = build_common.load_site_config()
    assert (
        cfg["data_base_url"]
        == "https://proj.supabase.co/storage/v1/object/public/site-data"
    )


def test_load_site_config_explicit_data_base_url_wins(tmp_path, monkeypatch):
    cfg_path = tmp_path / "site_config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "supabase_url": "https://proj.supabase.co",
                "data_base_url": "https://cdn.example/data",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(build_common, "SITE_CONFIG", cfg_path)
    cfg = build_common.load_site_config()
    assert cfg["data_base_url"] == "https://cdn.example/data"


# ── payload_unchanged ───────────────────────────────────────────────
def test_payload_unchanged_missing_file(tmp_path):
    assert build_common.payload_unchanged(tmp_path / "no.json", {"a": 1}) is False


def test_payload_unchanged_corrupt_json(tmp_path):
    p = tmp_path / "cards.json"
    p.write_text("{not json")
    assert build_common.payload_unchanged(p, {"a": 1}) is False


def test_payload_unchanged_non_dict(tmp_path):
    # 合法 JSON 但非 dict（列表）应判定为已变化，而非 .items() 崩溃
    p = tmp_path / "cards.json"
    p.write_text("[1, 2, 3]")
    assert build_common.payload_unchanged(p, {"a": 1}) is False


def test_payload_unchanged_only_timestamp_differs(tmp_path):
    p = tmp_path / "cards.json"
    p.write_text('{"generated_at": "old", "cards": []}')
    assert (
        build_common.payload_unchanged(p, {"generated_at": "new", "cards": []}) is True
    )


def test_payload_unchanged_data_changed(tmp_path):
    p = tmp_path / "cards.json"
    p.write_text('{"generated_at": "old", "cards": [1]}')
    assert (
        build_common.payload_unchanged(p, {"generated_at": "new", "cards": [2]}) is False
    )


# ── bump_cache_buster ───────────────────────────────────────────────
def test_bump_cache_buster_missing_html_noop(tmp_path):
    # html 不存在时不应报错
    build_common.bump_cache_buster(tmp_path / "no.html", "cards-data.js", b"x")


def test_bump_cache_buster_updates_version(tmp_path):
    html = tmp_path / "index.html"
    html.write_text('<script src="assets/cards-data.js?v=old"></script>')
    build_common.bump_cache_buster(html, "cards-data.js", b"hello")
    digest = hashlib.md5(b"hello").hexdigest()[:8]
    assert f"cards-data.js?v={digest}" in html.read_text()


def test_bump_cache_buster_idempotent(tmp_path):
    html = tmp_path / "index.html"
    html.write_text('<script src="assets/cards-data.js?v=old"></script>')
    build_common.bump_cache_buster(html, "cards-data.js", b"hello")
    first = html.read_text()
    build_common.bump_cache_buster(html, "cards-data.js", b"hello")
    assert html.read_text() == first


def test_bump_cache_buster_only_matches_target(tmp_path):
    html = tmp_path / "index.html"
    html.write_text(
        '<script src="assets/cards-data.js?v=old"></script>\n'
        '<script src="assets/wants-data.js?v=keep"></script>'
    )
    build_common.bump_cache_buster(html, "cards-data.js", b"hello")
    text = html.read_text()
    assert "wants-data.js?v=keep" in text
    assert "cards-data.js?v=old" not in text


# ── load_previous_enrichment ────────────────────────────────────────
def test_load_prev_missing_file(tmp_path):
    assert build_common.load_previous_enrichment(tmp_path / "no.json") == {}


def test_load_prev_corrupt_json(tmp_path):
    p = tmp_path / "cards.json"
    p.write_text("{bad")
    assert build_common.load_previous_enrichment(p) == {}


def test_load_prev_indexes_by_set_number_lang(tmp_path):
    p = tmp_path / "cards.json"
    p.write_text(
        '{"cards": [{"set": "neo", "number": "111", "lang": "en", "name_en": "X"}]}'
    )
    prev = build_common.load_previous_enrichment(p)
    assert "neo|111|en" in prev
    assert prev["neo|111|en"]["name_en"] == "X"


def test_load_prev_skips_error_cards(tmp_path):
    p = tmp_path / "cards.json"
    p.write_text(
        '{"cards": [{"set": "neo", "number": "111", "lang": "en", "error": "not_found"}, '
        '{"set": "neo", "number": "222", "lang": "en", "name_en": "Y"}]}'
    )
    prev = build_common.load_previous_enrichment(p)
    assert "neo|222|en" in prev
    assert "neo|111|en" not in prev


def test_load_prev_wants_key(tmp_path):
    p = tmp_path / "wants.json"
    p.write_text(
        '{"wants": [{"set": "neo", "number": "111", "lang": "en", "name_en": "Z"}]}'
    )
    prev = build_common.load_previous_enrichment(p, list_key="wants")
    assert "neo|111|en" in prev


# ── load_site_config ────────────────────────────────────────────────
def test_load_site_config_normal(monkeypatch, tmp_path):
    cfg = tmp_path / "site_config.json"
    cfg.write_text('{"title": "T", "subtitle": "S"}')
    monkeypatch.setattr(build_common, "SITE_CONFIG", cfg)
    assert build_common.load_site_config() == {"title": "T", "subtitle": "S"}


def test_load_site_config_missing_returns_default(monkeypatch, tmp_path):
    monkeypatch.setattr(build_common, "SITE_CONFIG", tmp_path / "no.json")
    cfg = build_common.load_site_config()
    assert cfg["title"] and cfg["subtitle"]


def test_load_site_config_corrupt_returns_default(monkeypatch, tmp_path):
    cfg = tmp_path / "site_config.json"
    cfg.write_text("{bad")
    monkeypatch.setattr(build_common, "SITE_CONFIG", cfg)
    cfg = build_common.load_site_config()
    # 损坏时回退默认配置，不抛异常
    assert cfg["title"] and cfg["subtitle"]


# ── pick_images ─────────────────────────────────────────────────────
def test_pick_images_from_image_uris():
    card = {"image_uris": {"small": "s", "normal": "n", "large": "l"}}
    assert build_common.pick_images(card) == {
        "small": "s",
        "normal": "n",
        "large": "l",
    }


def test_pick_images_from_card_faces():
    card = {"card_faces": [{"image_uris": {"small": "s", "normal": "n", "large": "l"}}]}
    assert build_common.pick_images(card) == {
        "small": "s",
        "normal": "n",
        "large": "l",
    }


def test_pick_images_empty():
    assert build_common.pick_images({}) == {"small": "", "normal": "", "large": ""}


# ── pick_text ───────────────────────────────────────────────────────
def test_pick_text_single_face_printed_first():
    card = {
        "printed_text": "PT",
        "oracle_text": "OT",
        "printed_type_line": "PTL",
        "type_line": "TL",
    }
    text, tl = build_common.pick_text(card)
    assert text == "PT"
    assert tl == "PTL"


def test_pick_text_double_face_joined():
    card = {
        "card_faces": [
            {"printed_text": "A", "printed_type_line": "TA"},
            {"printed_text": "B", "printed_type_line": "TB"},
        ]
    }
    text, tl = build_common.pick_text(card)
    assert text == "A\n//\nB"
    assert tl == "TA // TB"


def test_pick_text_empty():
    text, tl = build_common.pick_text({})
    assert text == "" and tl == ""


# ── pick_type_line_en ───────────────────────────────────────────────
def test_type_line_en_root():
    assert build_common.pick_type_line_en({"type_line": "Creature"}) == "Creature"


def test_type_line_en_from_faces():
    card = {"card_faces": [{"type_line": "Land"}, {"type_line": "Creature"}]}
    assert build_common.pick_type_line_en(card) == "Land // Creature"


def test_type_line_en_empty():
    assert build_common.pick_type_line_en({}) == ""


# ── classify_types ──────────────────────────────────────────────────
def test_classify_empty():
    assert build_common.classify_types("") == ["other"]


def test_classify_single():
    assert build_common.classify_types("Creature") == ["creature"]


def test_classify_multi():
    assert build_common.classify_types("Artifact Creature") == ["creature", "artifact"]


def test_classify_unknown():
    assert build_common.classify_types("Planesaurus") == ["other"]


# ── pick_mana ───────────────────────────────────────────────────────
def test_pick_mana_single():
    mc, cmc = build_common.pick_mana({"mana_cost": "{1}{R}", "cmc": 2})
    assert mc == "{1}{R}"
    assert cmc == 2.0


def test_pick_mana_double_face():
    card = {"card_faces": [{"mana_cost": "{R}"}, {"mana_cost": ""}]}
    mc, cmc = build_common.pick_mana(card)
    assert mc == "{R} // -"
    assert cmc == 0.0


def test_pick_mana_cmc_str_and_none():
    assert build_common.pick_mana({"cmc": "3"})[1] == 3.0
    assert build_common.pick_mana({"cmc": None})[1] == 0.0
    assert build_common.pick_mana({"cmc": "abc"})[1] == 0.0


# ── enrich_fields_from_scryfall ─────────────────────────────────────
def test_enrich_fields_combines():
    fields = build_common.enrich_fields_from_scryfall(
        {"type_line": "Artifact Creature", "mana_cost": "{2}", "cmc": 2}
    )
    assert fields["type_line_en"] == "Artifact Creature"
    assert fields["types"] == ["creature", "artifact"]
    assert fields["mana_cost"] == "{2}"
    assert fields["cmc"] == 2.0


# ── base_from_cached / base_from_card ───────────────────────────────
def test_base_from_cached_fills_defaults():
    base = build_common.base_from_cached({}, "neo", "111", "en")
    assert base["set"] == "neo"
    assert base["number"] == "111"
    assert base["lang"] == "en"
    assert base["image"] == {"small": "", "normal": "", "large": ""}
    assert base["cmc"] == 0


class _FakeClient:
    def __init__(self, zh="中名"):
        self._zh = zh

    def fetch_zh_name(self, set_code, number):
        return self._zh


def test_base_from_card_zhs_uses_printed_no_client():
    card = {
        "name": "Sol Ring",
        "printed_name": "阳光戒",
        "type_line": "Artifact",
        "cmc": 1,
    }
    # zhs 分支不调 client，传 None 也不应崩
    base = build_common.base_from_card(card, None, "neo", "111", "zhs")
    assert base["name_zh"] == "阳光戒"
    assert base["name_en"] == "Sol Ring"


def test_base_from_card_en_fetches_zh_name():
    card = {"name": "Sol Ring", "type_line": "Artifact", "cmc": 1, "lang": "en"}
    client = _FakeClient(zh="阳光戒")
    base = build_common.base_from_card(card, client, "neo", "111", "en")
    assert base["name_zh"] == "阳光戒"
    assert base["image_lang"] == "en"


# ── stable_payload_bytes ────────────────────────────────────────────
def test_stable_payload_bytes_excludes_generated_at():
    payload = {"generated_at": "2026-07-14", "cards": [1, 2], "count": 2}
    text = build_common.stable_payload_bytes(payload, "window.__MTG_DATA__").decode()
    assert text.startswith("window.__MTG_DATA__=")
    assert text.endswith(";\n")
    assert "generated_at" not in text
    # compact 序列化（separators=(',', ':')，无空格）；剥掉 var= 前缀与 ;\n 后缀后应还原剔除时间戳的 dict
    body = text[len("window.__MTG_DATA__="):-2]
    assert json.loads(body) == {"cards": [1, 2], "count": 2}


# ── ScryfallClient.fetch_zh_name 缓存策略 ───────────────────────────
def test_fetch_zh_name_caches_real_response(monkeypatch, tmp_path):
    # mtgch 正常返回应缓存（有名字写名字），避免每次重建都重拉
    monkeypatch.setattr(build_common, "CACHE_DIR", tmp_path)
    client = build_common.ScryfallClient(use_disk_cache=True)

    class _Resp:
        def json(self):
            return {"zhs_name": "阳光戒"}

    monkeypatch.setattr(client, "get", lambda *a, **k: _Resp())
    cache_path = tmp_path / "zhname_neo_111.txt"

    assert client.fetch_zh_name("neo", "111") == "阳光戒"
    assert cache_path.exists()
    assert cache_path.read_text(encoding="utf-8") == "阳光戒"


def test_fetch_zh_name_does_not_cache_transient_failure(monkeypatch, tmp_path):
    # 瞬时故障（超时/5xx/非法 JSON）不应缓存，否则会把“暂时拿不到”固化成 30 天阴性
    monkeypatch.setattr(build_common, "CACHE_DIR", tmp_path)
    client = build_common.ScryfallClient(use_disk_cache=True)

    def boom(*a, **k):
        raise build_common.requests.RequestException("timeout")

    monkeypatch.setattr(client, "get", boom)
    cache_path = tmp_path / "zhname_neo_111.txt"

    assert client.fetch_zh_name("neo", "111") == ""
    assert not cache_path.exists(), "瞬时故障不应写入缓存哨兵"


# ── ScryfallClient.fetch_card 缓存回退策略 ──────────────────────────
def _make_response(data):
    class _Resp:
        def json(self):
            return data
    return _Resp()


def test_fetch_card_cache_hit(monkeypatch, tmp_path):
    """TTL 内的缓存直接返回，不调 API"""
    monkeypatch.setattr(build_common, "CACHE_DIR", tmp_path)
    client = build_common.ScryfallClient(use_disk_cache=True)
    cache = tmp_path / "neo_111_en.json"
    cache.write_text(json.dumps({"name": "Sol Ring", "lang": "en"}), encoding="utf-8")

    def fail(*a, **k):
        raise AssertionError("不应调用 API")

    monkeypatch.setattr(client, "get", fail)
    result = client.fetch_card("neo", "111", "en")
    assert result["name"] == "Sol Ring"


def test_fetch_card_404_returns_none(monkeypatch, tmp_path):
    """所有 URL 都 404 时返回 None（not_found）"""
    monkeypatch.setattr(build_common, "CACHE_DIR", tmp_path)
    client = build_common.ScryfallClient(use_disk_cache=True)

    def mock_get(url, **k):
        resp = build_common.requests.Response()
        resp.status_code = 404
        err = build_common.requests.HTTPError(response=resp)
        raise err

    monkeypatch.setattr(client, "get", mock_get)
    assert client.fetch_card("neo", "111", "en") is None


def test_fetch_card_network_error_fallback_to_expired_cache(monkeypatch, tmp_path):
    """网络错误 + 有过期缓存 -> 回退旧缓存"""
    monkeypatch.setattr(build_common, "CACHE_DIR", tmp_path)
    client = build_common.ScryfallClient(use_disk_cache=True)
    cache = tmp_path / "neo_111_en.json"
    cache.write_text(json.dumps({"name": "Sol Ring", "lang": "en"}), encoding="utf-8")
    # 让缓存看起来已过期
    import os
    old_time = cache.stat().st_mtime - build_common.CACHE_TTL - 1
    os.utime(cache, (old_time, old_time))

    def mock_get(url, **k):
        raise build_common.requests.ConnectionError("timeout")

    monkeypatch.setattr(client, "get", mock_get)
    result = client.fetch_card("neo", "111", "en")
    assert result is not None
    assert result["name"] == "Sol Ring"


def test_fetch_card_network_error_no_cache_returns_none(monkeypatch, tmp_path):
    """网络错误 + 无缓存 -> None"""
    monkeypatch.setattr(build_common, "CACHE_DIR", tmp_path)
    client = build_common.ScryfallClient(use_disk_cache=True)

    def mock_get(url, **k):
        raise build_common.requests.ConnectionError("timeout")

    monkeypatch.setattr(client, "get", mock_get)
    assert client.fetch_card("neo", "111", "en") is None
