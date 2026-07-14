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
    normalize_qty,
    normalize_strict,
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


# card_line_to_fields
def test_card_line_basic():
    s, n, lang,f, q = card_line_to_fields(["neo", "111"])
    assert (s, n, lang,f, q) == ("neo", "111", "en", False, 1)


def test_card_line_with_qty():
    s, n, lang,f, q = card_line_to_fields(["2x", "neo", "111"])
    assert (s, n, lang,f, q) == ("neo", "111", "en", False, 2)


def test_card_line_with_lang_foil():
    s, n, lang,f, q = card_line_to_fields(["neo", "111", "z", "1"])
    assert (s, n, lang,f, q) == ("neo", "111", "zhs", True, 1)


def test_card_line_set_lowercased():
    s, *_ = card_line_to_fields(["NEO", "111"])
    assert s == "neo"


def test_card_line_too_few_raises():
    with pytest.raises(ParseError):
        card_line_to_fields(["neo"])


def test_card_line_empty_raises():
    with pytest.raises(ParseError):
        card_line_to_fields([])


def test_card_line_too_many_raises():
    with pytest.raises(ParseError, match="字段过多"):
        card_line_to_fields(["neo", "111", "e", "1", "extra"])


def test_card_line_unknown_token_raises():
    with pytest.raises(ParseError, match="无法识别"):
        card_line_to_fields(["neo", "111", "xyz"])


def test_card_line_duplicate_lang_raises():
    with pytest.raises(ParseError, match="语言字段重复"):
        card_line_to_fields(["neo", "111", "e", "z"])


def test_card_line_duplicate_foil_raises():
    with pytest.raises(ParseError, match="闪字段重复"):
        card_line_to_fields(["neo", "111", "0", "1"])


# want_line_to_fields
def test_want_line_basic():
    s, n, lang,f, q, m, note = want_line_to_fields("neo 111")
    assert (s, n, lang,f, q, m, note) == ("neo", "111", "en", False, 1, False, "")


def test_want_line_full():
    s, n, lang,f, q, m, note = want_line_to_fields("2x neo 111 z 1 1")
    assert (s, n, lang,f, q, m) == ("neo", "111", "zhs", True, 2, True)
    assert note == ""


def test_want_line_with_note():
    s, n, lang,f, q, m, note = want_line_to_fields("neo 111 | 急需")
    assert note == "急需"


def test_want_line_too_many_fields_raises():
    with pytest.raises(ParseError):
        want_line_to_fields("neo 111 z 1 1 extra")


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
