/* Strict browser/Node parser for the inventory and wants text formats. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MTGInventoryParser = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const LANG_INPUT = {
    "": "en",
    e: "en",
    en: "en",
    eng: "en",
    english: "en",
    英文: "en",
    z: "zhs",
    zh: "zhs",
    zhs: "zhs",
    cn: "zhs",
    中文: "zhs",
    简中: "zhs",
    j: "ja",
    ja: "ja",
    jp: "ja",
    日文: "ja",
    日语: "ja",
    o: "other",
    other: "other",
    others: "other",
    其他: "other",
  };
  const FOIL_TRUE = new Set(["1", "true", "yes", "y", "是", "闪", "闪卡", "foil", "f"]);
  const FOIL_FALSE = new Set(["", "0", "false", "no", "n", "否", "非闪", "nf"]);
  const MUST_TRUE = new Set(["1", "yes", "y", "是", "指定", "必须"]);
  const MUST_FALSE = new Set(["", "0", "no", "n", "否", "可替", "任意"]);
  const INTEGER_RE = /^[+-]?\d+$/;
  const QTY_X_RE = /^(?:(\d+)x|x(\d+))$/i;
  const DECIMAL_RE = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;

  function cellString(value) {
    return value == null ? "" : String(value).trim();
  }

  function normalizeLang(value) {
    const key = cellString(value).toLowerCase().replace(/　/g, "");
    if (Object.prototype.hasOwnProperty.call(LANG_INPUT, key)) return LANG_INPUT[key];
    throw new Error(`语言无效「${value}」（仅支持：e=英 / z=中 / j=日 / o=其他）`);
  }

  function normalizeFoil(value) {
    const key = cellString(value).toLowerCase();
    if (FOIL_TRUE.has(key)) return true;
    if (FOIL_FALSE.has(key)) return false;
    throw new Error(`闪卡无效「${value}」（仅支持：空/0=否，1=是）`);
  }

  function normalizeMust(value) {
    const key = cellString(value).toLowerCase();
    if (MUST_TRUE.has(key)) return true;
    if (MUST_FALSE.has(key)) return false;
    throw new Error(`版本要求无效「${value}」（空/0=可替，1=必须此版）`);
  }

  function normalizeQty(value) {
    const raw = cellString(value);
    if (!raw) return 1;
    const x = raw.match(QTY_X_RE);
    const normalized = x ? x[1] || x[2] : raw;
    if (!INTEGER_RE.test(normalized)) throw new Error(`数量须为整数，得到「${value}」`);
    const qty = Number(normalized);
    if (!Number.isSafeInteger(qty) || qty < 1) {
      throw new Error(`数量须 ≥ 1，得到「${value}」`);
    }
    return qty;
  }

  function normalizePrice(value) {
    const raw = cellString(value);
    if (!raw) return 0;
    if (!DECIMAL_RE.test(raw)) {
      throw new Error(`价格无效「${value}」（空=0 市价，>0 固定价）`);
    }
    const price = Number(raw);
    if (!Number.isFinite(price) || price < 0) {
      throw new Error(`价格须 ≥ 0，得到「${value}」`);
    }
    return price;
  }

  function splitLine(line, maxFields) {
    let raw = cellString(line);
    if (!raw || raw.startsWith("#")) return null;
    let note = "";
    const hash = raw.indexOf("#");
    if (hash >= 0) {
      note = raw.slice(hash + 1).trim();
      raw = raw.slice(0, hash);
    }
    const parts = raw.split(/\s+/).filter(Boolean);
    if (parts.length < 4) throw new Error(`至少需要 set number lang foil：${line}`);
    if (parts.length > maxFields) throw new Error(`字段过多：${line}`);
    return { parts, note };
  }

  function parseInventoryLine(line) {
    const parsed = splitLine(line, 6);
    if (!parsed) return null;
    const { parts, note } = parsed;
    return {
      set_code: parts[0].toLowerCase(),
      number: parts[1],
      lang: normalizeLang(parts[2]),
      foil: normalizeFoil(parts[3]),
      quantity: parts.length > 4 ? normalizeQty(parts[4]) : 1,
      price: parts.length > 5 ? normalizePrice(parts[5]) : 0,
      note,
    };
  }

  function parseWantLine(line) {
    const parsed = splitLine(line, 7);
    if (!parsed) return null;
    const { parts, note } = parsed;
    return {
      set_code: parts[0].toLowerCase(),
      number: parts[1],
      lang: normalizeLang(parts[2]),
      foil: normalizeFoil(parts[3]),
      quantity: parts.length > 4 ? normalizeQty(parts[4]) : 1,
      must: parts.length > 5 ? normalizeMust(parts[5]) : false,
      price: parts.length > 6 ? normalizePrice(parts[6]) : 0,
      note,
    };
  }

  function parseText(text, view) {
    const parse = view === "want" ? parseWantLine : parseInventoryLine;
    const rows = [];
    const errors = [];
    String(text || "")
      .split(/\r?\n/)
      .forEach((line, index) => {
        try {
          const row = parse(line);
          if (row) rows.push(row);
        } catch (error) {
          errors.push(`第 ${index + 1} 行：${error.message}`);
        }
      });
    return { rows, errors };
  }

  return {
    normalizeLang,
    normalizeFoil,
    normalizeMust,
    normalizeQty,
    normalizePrice,
    parseInventoryLine,
    parseWantLine,
    parseText,
  };
});
