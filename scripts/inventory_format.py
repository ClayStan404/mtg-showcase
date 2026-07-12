#!/usr/bin/env python3
"""统一库存字段约定：语言 e/z/j/o（空默认 e），闪 0/1/空，数量 空=1。"""

from __future__ import annotations

import re
from typing import Any

# 表格 / 用户输入 → 内部 lang 码（展示与 Scryfall）
# e=英文；空也默认英文。o(其他)：展示「其他」，拉图时回退英文印刷
LANG_INPUT_MAP = {
    "": "en",
    "e": "en",
    "en": "en",
    "eng": "en",
    "english": "en",
    "英文": "en",
    "z": "zhs",
    "zh": "zhs",
    "zhs": "zhs",
    "cn": "zhs",
    "中文": "zhs",
    "简中": "zhs",
    "j": "ja",
    "ja": "ja",
    "jp": "ja",
    "日文": "ja",
    "日语": "ja",
    "o": "other",
    "other": "other",
    "others": "other",
    "其他": "other",
}

# 仅允许以上可解析输入；未知则报错（严格模式）
ALLOWED_LANG_INPUTS = set(LANG_INPUT_MAP.keys())

LANG_LABEL = {
    "en": "英文",
    "zhs": "简中",
    "ja": "日文",
    "other": "其他",
}

# Scryfall API 用的 lang（other 回退 en）
SCRYFALL_LANG = {
    "en": "en",
    "zhs": "zhs",
    "ja": "ja",
    "other": "en",
}

# 闪：1 / 是 / foil / f / 闪 → True；0 / 否 / 空 → False
FOIL_TRUE = {"1", "true", "yes", "y", "是", "闪", "闪卡", "foil", "f"}
FOIL_FALSE = {"0", "false", "no", "n", "否", "非闪", "nf", ""}

QTY_RE = re.compile(r"^(?:(\d+)x|x(\d+))$", re.I)
SLUG_RE = re.compile(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+")


class ParseError(Exception):
    def __init__(self, message: str, line: int | None = None):
        self.line = line
        super().__init__(message)


REQUIRED_META_FIELDS = ("seller", "city", "contact")
_META_FIELD_LABELS = {"seller": "seller", "city": "city", "contact": "contact"}


def validate_meta(meta: dict[str, str], source: str = "") -> list[str]:
    """seller / city / contact 必填，返回缺失字段的错误消息列表。"""
    errors: list[str] = []
    for field in REQUIRED_META_FIELDS:
        if not (meta.get(field) or "").strip():
            prefix = f"[{source}] " if source else ""
            errors.append(f"{prefix}缺少必填项 # {field}:")
    return errors


def slugify(value: str, fallback: str = "seller") -> str:
    s = SLUG_RE.sub("-", (value or "").strip()).strip("-").lower()
    return s or fallback


def cell_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value).strip()


def normalize_lang(raw: Any, *, strict: bool = True) -> str:
    """返回内部 lang：en / zhs / ja / other。"""
    s = cell_str(raw).lower()
    # 兼容全角
    s = s.replace("　", "").strip()
    if s in LANG_INPUT_MAP:
        return LANG_INPUT_MAP[s]
    if not strict:
        return "en"
    raise ParseError(f"语言无效「{raw}」（仅支持：e=英 / z=中 / j=日 / o=其他；空默认 e）")


def normalize_foil(raw: Any, *, strict: bool = True) -> bool:
    s = cell_str(raw).lower()
    if s in FOIL_TRUE:
        return True
    if s in FOIL_FALSE:
        return False
    if not strict:
        return False
    raise ParseError(f"闪卡无效「{raw}」（仅支持：空/0=否，1=是）")


def normalize_qty(raw: Any, *, strict: bool = True) -> int:
    s = cell_str(raw)
    if s == "":
        return 1
    m = QTY_RE.match(s)
    if m:
        return int(m.group(1) or m.group(2))
    try:
        n = int(float(s))
    except ValueError as e:
        if not strict:
            return 1
        raise ParseError(f"数量无效「{raw}」") from e
    if n < 1:
        if not strict:
            return 1
        raise ParseError(f"数量须 ≥ 1，得到「{raw}」")
    return n


def lang_label(lang: str) -> str:
    return LANG_LABEL.get(lang, lang)


def scryfall_lang(lang: str) -> str:
    return SCRYFALL_LANG.get(lang, "en")


def normalize_strict(raw: Any, *, strict_mode: bool = True) -> bool:
    """求购：是否必须此印刷。空/0=其他版本也可，1=必须此版本。"""
    s = cell_str(raw).lower()
    if s in ("", "0", "no", "n", "否", "可替", "任意"):
        return False
    if s in ("1", "yes", "y", "是", "指定", "必须"):
        return True
    if not strict_mode:
        return False
    raise ParseError(f"版本要求无效「{raw}」（空/0=可替，1=必须此版）")


def card_line_to_fields(parts: list[str]) -> tuple[str, str, str, bool, int]:
    """解析卖牌库存行。

    格式: [Nx] set number [lang] [foil]
    lang/foil 可省略；foil 与 lang 用集合识别（兼容旧写法）。
    """
    if not parts:
        raise ParseError("空行")
    qty = 1
    if QTY_RE.match(parts[0]):
        qty = normalize_qty(parts[0])
        parts = parts[1:]
    if len(parts) < 2:
        raise ParseError("至少需要 系列 + 编号")

    set_code = parts[0].lower()
    number = parts[1]
    lang_raw = ""
    foil_raw = ""

    for token in parts[2:]:
        low = token.lower()
        if low in FOIL_TRUE or low in FOIL_FALSE:
            foil_raw = low
        elif low in LANG_INPUT_MAP:
            lang_raw = low
        else:
            lang_raw = low

    lang = normalize_lang(lang_raw)
    foil = normalize_foil(foil_raw) if foil_raw != "" else False
    if not foil:
        for token in parts[2:]:
            if cell_str(token).lower() in FOIL_TRUE:
                foil = True
                break

    return set_code, number, lang, foil, qty


def want_line_to_fields(line: str) -> tuple[str, str, str, bool, int, bool, str]:
    """解析求购行（指定印刷 + 是否必须此版）。

    格式: [Nx] set number [lang] [foil] [must]
          [| 备注]
    - lang: e/z/j/o，空=e
    - foil: 0/1，空=0
    - must: 0=其他版本也可，1=必须此印刷，空=0
    """
    note = ""
    raw = line.strip()
    if "|" in raw:
        raw, note = raw.split("|", 1)
        note = note.strip()
    parts = raw.split()
    if not parts:
        raise ParseError("空行")

    qty = 1
    if QTY_RE.match(parts[0]):
        qty = normalize_qty(parts[0])
        parts = parts[1:]
    if len(parts) < 2:
        raise ParseError("至少需要 系列 + 编号")
    if len(parts) > 5:
        raise ParseError("字段过多，格式: 系列 编号 [语言] [闪] [必须此版]")

    set_code = parts[0].lower()
    number = parts[1]
    # 位置固定：lang, foil, must
    lang = normalize_lang(parts[2] if len(parts) > 2 else "")
    foil = normalize_foil(parts[3] if len(parts) > 3 else "")
    must = normalize_strict(parts[4] if len(parts) > 4 else "")
    return set_code, number, lang, foil, qty, must, note
