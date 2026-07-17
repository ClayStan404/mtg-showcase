"""inventory_format 核心解析函数测试。

覆盖 normalize_qty / normalize_lang / normalize_foil / normalize_strict /
card_line_to_fields / want_line_to_fields / slugify 的边界情况。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from inventory_format import (  # noqa: E402
    ParseError,
    card_line_to_fields,
    normalize_foil,
    normalize_lang,
    normalize_price,
    normalize_qty,
    normalize_strict,
    note_hash,
    slugify,
    want_line_to_fields,
)


# normalize_qty
def test_qty_empty_default_1():
    assert normalize_qty("") == 1


def test_qty_plain_int():
    assert normalize_qty("3") == 3


def test_qty_nx_prefix():
    assert normalize_qty("2x") == 2
    assert normalize_qty("x4") == 4


def test_qty_non_integer_strict_raises():
    with pytest.raises(ParseError):
        normalize_qty("1.9")


def test_qty_zero_raises():
    with pytest.raises(ParseError):
        normalize_qty("0")


def test_qty_negative_raises():
    with pytest.raises(ParseError):
        normalize_qty("-1")


def test_qty_invalid_raises():
    with pytest.raises(ParseError):
        normalize_qty("abc")


def test_qty_non_integer_non_strict_returns_1():
    assert normalize_qty("1.9", strict=False) == 1


# normalize_lang
def test_lang_empty_default_en():
    assert normalize_lang("") == "en"


def test_lang_aliases():
    assert normalize_lang("e") == "en"
    assert normalize_lang("en") == "en"
    assert normalize_lang("英文") == "en"
    assert normalize_lang("z") == "zhs"
    assert normalize_lang("zh") == "zhs"
    assert normalize_lang("中文") == "zhs"
    assert normalize_lang("j") == "ja"
    assert normalize_lang("日文") == "ja"
    assert normalize_lang("o") == "other"
    assert normalize_lang("其他") == "other"


def test_lang_case_insensitive():
    assert normalize_lang("EN") == "en"
    assert normalize_lang("Ja") == "ja"


def test_lang_fullwidth_space():
    assert normalize_lang("　") == "en"


def test_lang_invalid_strict_raises():
    with pytest.raises(ParseError):
        normalize_lang("x")


def test_lang_invalid_non_strict_en():
    assert normalize_lang("x", strict=False) == "en"


# normalize_foil
def test_foil_true():
    for v in ("1", "是", "闪", "foil", "f"):
        assert normalize_foil(v) is True


def test_foil_false():
    for v in ("", "0", "否", "nf"):
        assert normalize_foil(v) is False


def test_foil_invalid_raises():
    with pytest.raises(ParseError):
        normalize_foil("xyz")


# normalize_strict
def test_strict_false():
    for v in ("", "0", "否", "可替", "任意"):
        assert normalize_strict(v) is False


def test_strict_true():
    for v in ("1", "是", "指定", "必须"):
        assert normalize_strict(v) is True


def test_strict_invalid_raises():
    with pytest.raises(ParseError):
        normalize_strict("xyz")


# normalize_price
def test_price_empty_default_0():
    assert normalize_price("") == 0.0


def test_price_int_str():
    assert normalize_price("50") == 50.0


def test_price_decimal_str():
    assert normalize_price("12.5") == 12.5


def test_price_negative_raises():
    with pytest.raises(ParseError):
        normalize_price("-1")


def test_price_invalid_raises():
    with pytest.raises(ParseError):
        normalize_price("abc")


# note_hash
def test_note_hash_stable_and_8chars():
    assert note_hash("签名") == note_hash("签名")
    assert len(note_hash("签名")) == 8


def test_note_hash_empty():
    assert note_hash("") == note_hash("")  # 稳定
    assert len(note_hash("")) == 8


# card_line_to_fields（位置格式 + # note + price，7 元组）
def test_card_line_basic():
    s, n, lang, f, q, p, note = card_line_to_fields("neo 111 e 0")
    assert (s, n, lang, f, q, p, note) == ("neo", "111", "en", False, 1, 0.0, "")


def test_card_line_with_qty():
    s, n, lang, f, q, p, note = card_line_to_fields("neo 111 e 0 3")
    assert (q, p, note) == (3, 0.0, "")


def test_card_line_with_price():
    s, n, lang, f, q, p, note = card_line_to_fields("neo 111 e 0 2 50")
    assert (q, p, note) == (2, 50.0, "")


def test_card_line_price_decimal():
    s, n, lang, f, q, p, note = card_line_to_fields("neo 111 e 0 1 12.5")
    assert p == 12.5


def test_card_line_with_note():
    s, n, lang, f, q, p, note = card_line_to_fields("neo 111 e 0 # 右下角破损")
    assert (q, p, note) == (1, 0.0, "右下角破损")


def test_card_line_full():
    s, n, lang, f, q, p, note = card_line_to_fields("neo 111 z 1 2 50 # 签名")
    assert (s, n, lang, f, q, p, note) == ("neo", "111", "zhs", True, 2, 50.0, "签名")


def test_card_line_note_with_spaces_stripped():
    s, n, lang, f, q, p, note = card_line_to_fields("neo 111 e 0 #   a b c  ")
    assert note == "a b c"


def test_card_line_set_lowercased():
    s, *_ = card_line_to_fields("NEO 111 e 0")
    assert s == "neo"


def test_card_line_price_before_qty_is_qty_footgun():
    # 反例（文档第 5 节）：sta 124 j 0 50 ≠ 1张50元，50 被当作 qty
    s, n, lang, f, q, p, note = card_line_to_fields("sta 124 j 0 50")
    assert (q, p) == (50, 0.0)


def test_card_line_too_few_raises():
    with pytest.raises(ParseError, match="中间字段不能省"):
        card_line_to_fields("neo 111")


def test_card_line_empty_raises():
    with pytest.raises(ParseError):
        card_line_to_fields("")


def test_card_line_too_many_raises():
    with pytest.raises(ParseError, match="字段过多"):
        card_line_to_fields("neo 111 e 0 1 50 extra")


def test_card_line_negative_price_raises():
    with pytest.raises(ParseError, match="价格须"):
        card_line_to_fields("neo 111 e 0 1 -5")


def test_card_line_invalid_price_raises():
    with pytest.raises(ParseError, match="价格无效"):
        card_line_to_fields("neo 111 e 0 1 abc")


# want_line_to_fields（位置格式 + # note + price，8 元组）
def test_want_line_basic():
    s, n, lang, f, q, m, p, note = want_line_to_fields("neo 111 e 0")
    assert (s, n, lang, f, q, m, p, note) == ("neo", "111", "en", False, 1, False, 0.0, "")


def test_want_line_with_must():
    s, n, lang, f, q, m, p, note = want_line_to_fields("neo 111 e 0 2 1")
    assert (q, m, p, note) == (2, True, 0.0, "")


def test_want_line_must_0_price_50():
    s, n, lang, f, q, m, p, note = want_line_to_fields("neo 111 e 0 2 0 50")
    assert (q, m, p, note) == (2, False, 50.0, "")


def test_want_line_full():
    s, n, lang, f, q, m, p, note = want_line_to_fields("neo 111 e 0 2 1 50 # 急收")
    assert (s, n, lang, f, q, m, p, note) == ("neo", "111", "en", False, 2, True, 50.0, "急收")


def test_want_line_note_only():
    s, n, lang, f, q, m, p, note = want_line_to_fields("neo 111 e 0 # 急需")
    assert (q, m, p, note) == (1, False, 0.0, "急需")


def test_want_line_too_few_raises():
    with pytest.raises(ParseError, match="中间字段不能省"):
        want_line_to_fields("neo 111")


def test_want_line_too_many_fields_raises():
    with pytest.raises(ParseError, match="字段过多"):
        want_line_to_fields("neo 111 e 0 2 1 50 extra")


# slugify
def test_slugify_chinese_kept():
    assert slugify("小明") == "小明"


def test_slugify_special_replaced():
    assert slugify("a b!c") == "a-b-c"


def test_slugify_empty_fallback():
    assert slugify("") == "seller"
    assert slugify("", "buyer") == "buyer"


def test_slugify_lowercased():
    assert slugify("Neo") == "neo"
