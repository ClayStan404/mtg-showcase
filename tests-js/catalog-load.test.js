"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const catalog = require("../assets/catalog-load.js");

test("isCatalogTimeout detects abort and timeout errors", () => {
  assert.equal(catalog.isCatalogTimeout({ name: "TimeoutError" }), true);
  assert.equal(catalog.isCatalogTimeout({ name: "AbortError" }), true);
  assert.equal(catalog.isCatalogTimeout({ name: "TypeError" }), false);
  assert.equal(catalog.isCatalogTimeout(null), false);
});

test("shouldUseStorageFallback rejects timeouts only", () => {
  assert.equal(catalog.shouldUseStorageFallback({ name: "TimeoutError" }), false);
  assert.equal(catalog.shouldUseStorageFallback({ name: "AbortError" }), false);
  assert.equal(catalog.shouldUseStorageFallback(new Error("HTTP 404")), true);
  assert.equal(catalog.shouldUseStorageFallback({ status: 500 }), true);
});
