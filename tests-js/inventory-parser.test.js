"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const parser = require("../assets/inventory-parser.js");

test("parses inventory and wants rows without truncating values", () => {
  assert.deepEqual(parser.parseInventoryLine("sta 124 j 1 2 50 # signed"), {
    set_code: "sta",
    number: "124",
    lang: "ja",
    foil: true,
    quantity: 2,
    price: 50,
    note: "signed",
  });
  assert.deepEqual(parser.parseWantLine("neo 111 e 0 3 1 12.5"), {
    set_code: "neo",
    number: "111",
    lang: "en",
    foil: false,
    quantity: 3,
    must: true,
    price: 12.5,
    note: "",
  });
});

test("supports the same common aliases and quantity forms as Python", () => {
  assert.equal(parser.normalizeLang("中文"), "zhs");
  assert.equal(parser.normalizeFoil("foil"), true);
  assert.equal(parser.normalizeMust("可替"), false);
  assert.equal(parser.normalizeQty("2x"), 2);
  assert.equal(parser.normalizeQty("x4"), 4);
});

test("rejects partial numeric and invalid boolean tokens", () => {
  for (const value of ["1.9", "2abc", "1e2", "NaN"]) {
    assert.throws(() => parser.normalizeQty(value));
  }
  for (const value of ["12x", "NaN", "Infinity", "-1"]) {
    assert.throws(() => parser.normalizePrice(value));
  }
  assert.throws(() => parser.normalizeFoil("sometimes"));
  assert.throws(() => parser.normalizeMust("maybe"));
});

test("parseText reports line numbers and keeps valid rows", () => {
  const result = parser.parseText("neo 1 e 0\nneo 2 e invalid\nneo 3 z 1 2", "sell");
  assert.equal(result.rows.length, 2);
  assert.equal(result.errors.length, 1);
  assert.match(result.errors[0], /^第 2 行：/);
});
