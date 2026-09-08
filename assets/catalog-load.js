/* Catalog load policy helpers (Storage-first Scheme C). Browser + Node. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MTGCatalogLoad = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function isCatalogTimeout(err) {
    const name = err && err.name;
    return name === "TimeoutError" || name === "AbortError";
  }

  /**
   * Storage timeout must not fall through to a stale Pages/inline catalog.
   * Other Storage failures (4xx/5xx/invalid JSON) may use local fallbacks.
   */
  function shouldUseStorageFallback(err) {
    return !isCatalogTimeout(err);
  }

  return {
    isCatalogTimeout,
    shouldUseStorageFallback,
  };
});
