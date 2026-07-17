"""export 脚本行格式化 + 解析器往返测试。

format_inventory_line / format_want_line 产出的 txt 行必须能被
card_line_to_fields / want_line_to_fields 无损解析回原值（round-trip），
保证 export -> build 的 txt 接口往返一致（id 合并键依赖 :.2f 对齐）。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from export_common import format_meta_header  # noqa: E402
from export_inventory_to_txt import format_inventory_line  # noqa: E402
from export_wants_to_txt import format_want_line  # noqa: E402
from inventory_format import card_line_to_fields, want_line_to_fields  # noqa: E402


def _inv_row(set_code, number, lang, foil, qty, price, note=""):
    return {
        "set_code": set_code, "number": number, "lang": lang, "foil": foil,
        "quantity": qty, "price": price, "note": note,
    }


def _want_row(set_code, number, lang, foil, qty, must, price, note=""):
    return {
        "set_code": set_code, "number": number, "lang": lang, "foil": foil,
        "quantity": qty, "must": must, "price": price, "note": note,
    }


# --- format_inventory_line ---
def test_inv_line_basic():
    assert format_inventory_line(_inv_row("sta", "124", "ja", False, 1, 0)) == "sta 124 j 0 1 0.00"


def test_inv_line_price_two_decimals():
    # price 一律 2 位（50 -> "50.00"），与 build 端 card_id 的 :.2f 对齐
    assert format_inventory_line(_inv_row("sta", "124", "ja", False, 2, 50)) == "sta 124 j 0 2 50.00"
    assert format_inventory_line(_inv_row("sta", "124", "ja", False, 1, 12.5)) == "sta 124 j 0 1 12.50"


def test_inv_line_foil_true():
    assert format_inventory_line(_inv_row("neo", "111", "en", True, 1, 0)) == "neo 111 e 1 1 0.00"


def test_inv_line_lang_tokens():
    assert format_inventory_line(_inv_row("x", "1", "en", False, 1, 0)).split()[2] == "e"
    assert format_inventory_line(_inv_row("x", "1", "zhs", False, 1, 0)).split()[2] == "z"
    assert format_inventory_line(_inv_row("x", "1", "ja", False, 1, 0)).split()[2] == "j"
    assert format_inventory_line(_inv_row("x", "1", "other", False, 1, 0)).split()[2] == "o"


def test_inv_line_note_appended():
    assert format_inventory_line(_inv_row("sta", "124", "ja", False, 2, 50, "签名")) == "sta 124 j 0 2 50.00 # 签名"


def test_inv_line_note_stripped():
    row = _inv_row("sta", "124", "ja", False, 1, 0, "  右下角破损  ")
    assert format_inventory_line(row).endswith("# 右下角破损")


# --- format_want_line ---
def test_want_line_basic():
    assert format_want_line(_want_row("neo", "111", "en", False, 1, False, 0)) == "neo 111 e 0 1 0 0.00"


def test_want_line_must_and_price():
    assert format_want_line(_want_row("neo", "111", "en", False, 2, True, 50)) == "neo 111 e 0 2 1 50.00"


def test_want_line_note():
    assert format_want_line(_want_row("neo", "111", "en", False, 2, True, 50, "急收")) == "neo 111 e 0 2 1 50.00 # 急收"


# --- round-trip: format -> parse 还原 ---
@pytest.mark.parametrize("lang", ["en", "zhs", "ja", "other"])
@pytest.mark.parametrize("foil", [False, True])
@pytest.mark.parametrize("price", [0, 50, 12.5, 9.99])
def test_inv_roundtrip(lang, foil, price):
    row = _inv_row("sta", "124", lang, foil, 3, price, "备注 x")
    s, n, lg, f, q, p, note = card_line_to_fields(format_inventory_line(row))
    assert (s, n, lg, f, q, p, note) == ("sta", "124", lang, foil, 3, float(f"{price:.2f}"), "备注 x")


@pytest.mark.parametrize("lang", ["en", "zhs", "ja", "other"])
@pytest.mark.parametrize("must", [False, True])
@pytest.mark.parametrize("price", [0, 50, 12.5])
def test_want_roundtrip(lang, must, price):
    row = _want_row("neo", "111", lang, False, 2, must, price, "急收")
    s, n, lg, f, q, m, p, note = want_line_to_fields(format_want_line(row))
    assert (s, n, lg, f, q, m, p, note) == ("neo", "111", lang, False, 2, must, float(f"{price:.2f}"), "急收")


def test_inv_roundtrip_no_note():
    row = _inv_row("sta", "124", "ja", False, 1, 0, "")
    s, n, lg, f, q, p, note = card_line_to_fields(format_inventory_line(row))
    assert note == ""


# --- meta header ---
def test_meta_header_format():
    h = format_meta_header("claystan", "上海", "QQ 417592443")
    assert h == "# seller: claystan\n# city: 上海\n# contact: QQ 417592443\n"


def test_meta_header_buyer_role():
    # wants export 用 role="buyer"，写 # buyer: 头（build_wants META_RE 接受 buyer|seller）
    h = format_meta_header("claystan", "武汉", "QQ 123", role="buyer")
    assert h == "# buyer: claystan\n# city: 武汉\n# contact: QQ 123\n"
