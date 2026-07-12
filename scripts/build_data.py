#!/usr/bin/env python3
"""Parse inventory.txt → enrich via Scryfall (+ mtgch for 中文名) → data/cards.json"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "inventory.txt"
DEFAULT_OUTPUT = ROOT / "data" / "cards.json"
SITE_CONFIG = ROOT / "site_config.json"

# 与 MTGImgDownloader 一致：短码 → Scryfall lang
LANG_MAP = {
    "": "en",
    "en": "en",
    "z": "zhs",
    "zhs": "zhs",
    "zh": "zhs",
    "j": "ja",
    "ja": "ja",
    "d": "de",
    "de": "de",
    "f": "fr",  # 仅当单独出现且不在 foil 集合时；解析时 foil 优先
    "fr": "fr",
    "k": "ko",
    "ko": "ko",
    "s": "es",
    "es": "es",
    "i": "it",
    "it": "it",
    "p": "pt",
    "pt": "pt",
    "r": "ru",
    "ru": "ru",
}

LANG_LABEL = {
    "en": "英文",
    "zhs": "简中",
    "ja": "日文",
    "de": "德文",
    "fr": "法文",
    "ko": "韩文",
    "es": "西文",
    "it": "意文",
    "pt": "葡文",
    "ru": "俄文",
}

FOIL_TOKENS = {"foil", "f", "1", "闪", "闪卡"}
QTY_RE = re.compile(r"^(?:(\d+)x|x(\d+))$", re.I)

# Scryfall: ≤10 req/s；保守一点
REQUEST_GAP = 0.12
USER_AGENT = "MTGShowcase/1.0 (personal inventory; github pages)"


def load_site_config() -> dict[str, Any]:
    if SITE_CONFIG.exists():
        return json.loads(SITE_CONFIG.read_text(encoding="utf-8"))
    return {
        "title": "我的万智牌库存",
        "subtitle": "实体卡展示 · 仅供浏览与联系",
        "contact": {
            "wechat": "",
            "email": "",
            "note": "有意向请通过下方方式联系，说明系列缩写 + 编号即可。",
        },
    }


def parse_inventory(path: Path) -> list[dict[str, Any]]:
    """解析库存文件。相同 key 合并数量。"""
    if not path.exists():
        raise FileNotFoundError(f"找不到库存文件: {path}")

    merged: OrderedDict[str, dict[str, Any]] = OrderedDict()

    with path.open(encoding="utf-8") as fh:
        for line_num, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            qty = 1

            # 可选数量前缀：2x / x3
            m = QTY_RE.match(parts[0])
            if m:
                qty = int(m.group(1) or m.group(2))
                parts = parts[1:]

            if len(parts) < 2:
                print(f"[warn] 第{line_num}行格式错误，跳过: {raw.rstrip()}", file=sys.stderr)
                continue

            set_code = parts[0].lower()
            number = parts[1]
            lang_code = ""
            is_foil = False

            for token in parts[2:]:
                low = token.lower()
                if low in FOIL_TOKENS:
                    is_foil = True
                else:
                    # 语言短码；f 已在 foil 集合里，不会落到这里表示法文
                    lang_code = "" if low == "en" else low

            scryfall_lang = LANG_MAP.get(lang_code, lang_code or "en")
            key = f"{set_code}|{number}|{scryfall_lang}|{'foil' if is_foil else 'nf'}"

            if key in merged:
                merged[key]["quantity"] += qty
            else:
                merged[key] = {
                    "set": set_code,
                    "number": number,
                    "lang": scryfall_lang,
                    "lang_raw": lang_code,
                    "foil": is_foil,
                    "quantity": qty,
                    "source_line": line_num,
                }

    return list(merged.values())


class ScryfallClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._last = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < REQUEST_GAP:
            time.sleep(REQUEST_GAP - elapsed)
        self._last = time.monotonic()

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        self._throttle()
        resp = self.session.get(url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        self._throttle()
        resp = self.session.post(url, timeout=60, **kwargs)
        resp.raise_for_status()
        return resp

    def fetch_card(self, set_code: str, number: str, lang: str) -> dict[str, Any] | None:
        """优先指定语言；失败回退英文印刷。"""
        urls = [
            f"https://api.scryfall.com/cards/{set_code}/{number}/{lang}",
        ]
        if lang != "en":
            urls.append(f"https://api.scryfall.com/cards/{set_code}/{number}")

        for url in urls:
            try:
                return self.get(url).json()
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    continue
                raise
        return None

    def fetch_zh_name(self, set_code: str, number: str) -> str:
        """mtgch 补充中文名（英文印刷时 printed_name 为空）。"""
        url = f"https://mtgch.com/api/v1/card/{set_code}/{number}/"
        try:
            data = self.get(url).json()
            return (
                data.get("zhs_name")
                or data.get("atomic_official_name")
                or data.get("atomic_translated_name")
                or ""
            )
        except Exception:
            return ""


def pick_images(card: dict[str, Any]) -> dict[str, str]:
    if card.get("image_uris"):
        uris = card["image_uris"]
        return {
            "small": uris.get("small", ""),
            "normal": uris.get("normal", ""),
            "large": uris.get("large", ""),
        }
    faces = card.get("card_faces") or []
    if faces and faces[0].get("image_uris"):
        uris = faces[0]["image_uris"]
        return {
            "small": uris.get("small", ""),
            "normal": uris.get("normal", ""),
            "large": uris.get("large", ""),
        }
    return {"small": "", "normal": "", "large": ""}


def pick_text(card: dict[str, Any]) -> tuple[str, str]:
    """返回 (牌面文字, 类型行)，优先印刷文本。"""
    if card.get("card_faces"):
        texts = []
        types = []
        for face in card["card_faces"]:
            t = face.get("printed_text") or face.get("oracle_text") or ""
            if t:
                texts.append(t)
            ty = face.get("printed_type_line") or face.get("type_line") or ""
            if ty:
                types.append(ty)
        return "\n//\n".join(texts), " // ".join(types)

    text = card.get("printed_text") or card.get("oracle_text") or ""
    type_line = card.get("printed_type_line") or card.get("type_line") or ""
    return text, type_line


def enrich(entries: list[dict[str, Any]], client: ScryfallClient) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    total = len(entries)

    for i, entry in enumerate(entries, 1):
        set_code = entry["set"]
        number = entry["number"]
        lang = entry["lang"]
        print(f"[{i}/{total}] {set_code} {number} {lang}{' foil' if entry['foil'] else ''}", flush=True)

        card = client.fetch_card(set_code, number, lang)
        if not card:
            print(f"  ! 未找到: {set_code} {number} {lang}", file=sys.stderr)
            results.append(
                {
                    "id": f"{set_code}-{number}-{lang}-{'f' if entry['foil'] else 'nf'}",
                    "set": set_code,
                    "set_name": set_code.upper(),
                    "number": number,
                    "lang": lang,
                    "lang_label": LANG_LABEL.get(lang, lang),
                    "foil": entry["foil"],
                    "quantity": entry["quantity"],
                    "name_en": "",
                    "name_zh": "",
                    "name_printed": "",
                    "type_line": "",
                    "text": "",
                    "image": pick_images({}),
                    "error": "not_found",
                }
            )
            continue

        name_en = card.get("name") or ""
        name_printed = card.get("printed_name") or ""
        # 双面牌
        if not name_printed and card.get("card_faces"):
            name_printed = card["card_faces"][0].get("printed_name") or ""

        name_zh = ""
        if lang == "zhs":
            name_zh = name_printed or name_en
        else:
            name_zh = client.fetch_zh_name(set_code, number)

        text, type_line = pick_text(card)
        images = pick_images(card)

        results.append(
            {
                "id": f"{set_code}-{number}-{lang}-{'f' if entry['foil'] else 'nf'}",
                "set": card.get("set") or set_code,
                "set_name": card.get("set_name") or set_code.upper(),
                "number": card.get("collector_number") or number,
                "lang": card.get("lang") or lang,
                "lang_label": LANG_LABEL.get(card.get("lang") or lang, lang),
                "foil": entry["foil"],
                "quantity": entry["quantity"],
                "name_en": name_en,
                "name_zh": name_zh,
                "name_printed": name_printed or name_en,
                "type_line": type_line,
                "text": text,
                "image": images,
                "scryfall_uri": card.get("scryfall_uri") or "",
            }
        )

    # 稳定排序：系列 + 编号 + 语言
    results.sort(key=lambda c: (c["set"], _num_key(c["number"]), c["lang"], not c["foil"]))
    return results


def _num_key(num: str) -> tuple:
    m = re.match(r"^(\d+)", str(num))
    return (int(m.group(1)) if m else 0, str(num))


def main() -> int:
    parser = argparse.ArgumentParser(description="从 inventory 生成网站用 cards.json")
    parser.add_argument("-i", "--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    entries = parse_inventory(args.inventory)
    if not entries:
        print("没有有效库存行", file=sys.stderr)
        return 1

    print(f"解析到 {len(entries)} 种卡（已合并重复）")
    client = ScryfallClient()
    cards = enrich(entries, client)

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "site": load_site_config(),
        "count": len(cards),
        "total_quantity": sum(c.get("quantity", 0) for c in cards),
        "cards": cards,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {args.output} （{payload['count']} 种 / 共 {payload['total_quantity']} 张）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
