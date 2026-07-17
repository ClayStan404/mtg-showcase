/* admin/admin.js -- admin SPA：Supabase CRUD + 双 tab + 批量/导入 + 立即发布。
 *
 * 复用 mtg-ui.js 的展示/筛选/分页（state / filters / matches / renderGrid / loadMore /
 * mountFilters / populateFilters / $ / escapeHtml / bindImgErrors / PLACEHOLDER_IMG /
 * PAGE_SIZE / closeAllDropdowns / setFiltersOpen / updateFilterToggle / syncScrim 等）。
 * override 全局 cardHtml（admin 版：price 展示 + 编辑/删除按钮，无购物车）。
 * 不加载 app.js；自实现 setView / renderAdminMeta / main / CRUD / 批量 / 导入。
 */
(function () {
  "use strict";

  // $ 由 mtg-ui.js 全局提供（admin.html 先于本文件加载 mtg-ui.js），不在此重复定义。
  const LANG_TOK = { e: "en", z: "zhs", j: "ja", o: "other" };
  const LANG_LABEL = { en: "英文", zhs: "简中", ja: "日文", other: "其他" };
  const SCRYFALL_LANG = { en: "en", zhs: "zhs", ja: "ja", other: "en" };
  const INVENTORY_FMT =
    "inventory:  set number lang foil [qty] [price] [# note]\n" +
    "  sta 124 j 0              1张 市价\n" +
    "  sta 124 j 0 2 50         2张 50/张\n" +
    "  sta 124 j 0 2 50 # 签名  2张 50 签名\n" +
    "  ❌ sta 124 j 0 50  ≠ 1张50元（50 会被当成 qty）→ 写 sta 124 j 0 1 50";
  const WANTS_FMT =
    "wants:  set number lang foil [qty] [must] [price] [# note]\n" +
    "  sta 124 j 0 2            2张 市价 可替\n" +
    "  sta 124 j 0 2 1 50       2张 50 必须此版\n" +
    "  sta 124 j 0 2 0 50       2张 50 可替（must 显式 0）";

  let uid = null;
  let profile = null;
  let displayIndex = new Map(); // `${set}|${number}|${lang}` -> cards.json 显示数据
  let previewTimer = null;

  // ---------- txt 解析（镜像 Python card_line_to_fields / want_line_to_fields）----------
  function normQty(s) {
    if (s == null || s === "") return 1;
    const n = parseInt(s, 10);
    if (!Number.isFinite(n) || n < 1) throw new Error("数量无效「" + s + "」");
    return n;
  }
  function normPrice(s) {
    if (s == null || s === "") return 0;
    const p = parseFloat(s);
    if (!Number.isFinite(p) || p < 0) throw new Error("价格无效「" + s + "」");
    return p;
  }
  function tokToLang(tok) {
    const v = LANG_TOK[(tok || "").toLowerCase()];
    if (!v) throw new Error("语言无效「" + tok + "」（仅 e/z/j/o）");
    return v;
  }

  function parseInventoryLine(line) {
    let note = "";
    let raw = line.trim();
    if (!raw || raw.startsWith("#")) return null;
    const hi = raw.indexOf("#");
    if (hi >= 0) { note = raw.slice(hi + 1).trim(); raw = raw.slice(0, hi); }
    const parts = raw.split(/\s+/).filter(Boolean);
    if (parts.length < 4) throw new Error("至少需要 set number lang foil：" + line);
    if (parts.length > 6) throw new Error("字段过多：" + line);
    return {
      set_code: parts[0].toLowerCase(), number: parts[1], lang: tokToLang(parts[2]),
      foil: parts[3] === "1", quantity: parts.length > 4 ? normQty(parts[4]) : 1,
      price: parts.length > 5 ? normPrice(parts[5]) : 0, note,
    };
  }

  function parseWantLine(line) {
    let note = "";
    let raw = line.trim();
    if (!raw || raw.startsWith("#")) return null;
    const hi = raw.indexOf("#");
    if (hi >= 0) { note = raw.slice(hi + 1).trim(); raw = raw.slice(0, hi); }
    const parts = raw.split(/\s+/).filter(Boolean);
    if (parts.length < 4) throw new Error("至少需要 set number lang foil：" + line);
    if (parts.length > 7) throw new Error("字段过多：" + line);
    return {
      set_code: parts[0].toLowerCase(), number: parts[1], lang: tokToLang(parts[2]),
      foil: parts[3] === "1", quantity: parts.length > 4 ? normQty(parts[4]) : 1,
      must: parts.length > 5 ? parts[5] === "1" : false,
      price: parts.length > 6 ? normPrice(parts[6]) : 0, note,
    };
  }

  function parseText(text, view) {
    const fn = view === "want" ? parseWantLine : parseInventoryLine;
    const rows = [];
    const errors = [];
    text.split(/\r?\n/).forEach((line, i) => {
      try {
        const r = fn(line);
        if (r) rows.push(r);
      } catch (e) {
        errors.push(`第 ${i + 1} 行：${e.message}`);
      }
    });
    return { rows, errors };
  }

  // ---------- 显示 join（cards.json 提供 name/image/type）----------
  function buildDisplayIndex() {
    const cards = (window.__MTG_DATA__ && window.__MTG_DATA__.cards) || [];
    const m = new Map();
    for (const c of cards) {
      const k = `${c.set}|${c.number}|${c.lang}`;
      if (!m.has(k)) m.set(k, c); // 首个命中即可（显示用，foil 不影响图/名）
    }
    displayIndex = m;
  }

  function rowToCard(row, view) {
    const k = `${row.set_code}|${row.number}|${row.lang}`;
    const d = displayIndex.get(k) || {};
    const hasImg = !!(d.image && (d.image.normal || d.image.small));
    const base = {
      id: row.id,
      set: row.set_code, number: row.number, lang: row.lang, foil: row.foil,
      quantity: row.quantity, price: Number(row.price) || 0, note: row.note || "",
      name_en: d.name_en || "", name_zh: d.name_zh || "", name_printed: d.name_printed || "",
      image: d.image || { small: "", normal: "", large: "" },
      type_line: d.type_line || "", type_line_en: d.type_line_en || "",
      types: d.types || [], mana_cost: d.mana_cost || "", cmc: d.cmc || 0, text: d.text || "",
      lang_label: LANG_LABEL[row.lang] || row.lang, scryfall_uri: d.scryfall_uri || "",
      _row: row,
      _needsImage: !hasImg, // join 不到图（新加、还没 build）-> 实时 Scryfall 兜底
    };
    if (view === "sell") {
      base.seller = (profile && profile.seller_name) || "";
      base.seller_id = uid; base.city = (profile && profile.city) || ""; base.contact = (profile && profile.contact) || "";
    } else {
      base.kind = row.must ? "exact" : "flex"; base.must = !!row.must;
      base.buyer = (profile && profile.seller_name) || "";
      base.buyer_id = uid; base.city = (profile && profile.city) || ""; base.contact = (profile && profile.contact) || "";
    }
    return base;
  }

  // ---------- admin cardHtml（override 全局）----------
  function adminCardHtml(c) {
    const isWant = state.view === "want";
    const price = Number(c.price) || 0;
    const priceBadge = price > 0 ? `<span class="card-price">¥${escapeHtml(price.toFixed(2))}</span>` : "";
    const name = c.name_en || c.name_zh || `${(c.set || "").toUpperCase()} #${c.number}`;
    const img = (c.image && (c.image.normal || c.image.small)) || PLACEHOLDER_IMG;
    const flags = [
      c.foil ? '<span class="flag flag-foil">闪</span>' : "",
      c.quantity > 1 ? `<span class="flag flag-qty">×${escapeHtml(String(c.quantity))}</span>` : "",
      isWant ? (c.must ? '<span class="flag flag-exact">必须</span>' : '<span class="flag flag-any">可替</span>') : "",
    ].join("");
    return `<div class="card" data-id="${escapeHtml(c.id)}">
      <div class="card-media">
        <div class="card-img-wrap"><img src="${escapeHtml(img)}" alt="${escapeHtml(name)}" loading="lazy" decoding="async" /></div>
        ${priceBadge}
      </div>
      <div class="card-body">
        <p class="card-name">${escapeHtml(name)}</p>
        <div class="card-meta"><span>${escapeHtml((c.set || "").toUpperCase())} #${escapeHtml(c.number)}</span><span>${escapeHtml(c.lang_label || "")}</span></div>
        ${flags ? `<div class="card-flags">${flags}</div>` : ""}
        ${c.note ? `<p class="card-note">${escapeHtml(c.note)}</p>` : ""}
        <div class="card-admin-actions">
          <button type="button" class="btn btn-ghost btn-sm" data-act="edit" data-id="${escapeHtml(c.id)}">编辑</button>
          <button type="button" class="btn btn-danger-ghost btn-sm" data-act="del" data-id="${escapeHtml(c.id)}">删除</button>
        </div>
      </div>
    </div>`;
  }

  // 实时 Scryfall 兜底：join 不到图/名的卡（刚加、还没 build）渲染后异步拉图 + 名。
  // 由 mtg-ui 的 decorateCards（renderGrid / loadMore 后调用）触发；admin 注册此 hook。
  function adminDecorateCard(card, el) {
    if (!card._needsImage) return;
    const img = el.querySelector("img");
    if (!img || img.dataset.sfFetched === "1") return;
    img.dataset.sfFetched = "1"; // 防重入（重渲染同一张不重复拉）
    const slang = SCRYFALL_LANG[card.lang] || "en";
    fetch(`https://api.scryfall.io/cards/${encodeURIComponent(card.set)}/${encodeURIComponent(card.number)}/${slang}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (!j) return;
        const url = j.image_uris && (j.image_uris.normal || j.image_uris.small);
        if (url) img.src = url;
        const name = j.name || "";
        if (name) {
          img.alt = name;
          const nameEl = el.querySelector(".card-name");
          if (nameEl) nameEl.textContent = name;
        }
      })
      .catch(() => {});
  }

  // ---------- Supabase 读写 ----------
  async function loadInventory() {
    const c = await MTGSupabase.getClient();
    const { data, error } = await c.from("inventory").select("*").eq("seller_id", uid)
      .order("updated_at", { ascending: false });
    if (error) throw error;
    return data || [];
  }
  async function loadWants() {
    const c = await MTGSupabase.getClient();
    const { data, error } = await c.from("wants").select("*").eq("buyer_id", uid)
      .order("updated_at", { ascending: false });
    if (error) throw error;
    return data || [];
  }
  async function loadProfile() {
    const c = await MTGSupabase.getClient();
    const { data, error } = await c.from("profiles").select("*").eq("id", uid).single();
    if (error && error.code !== "PGRST116") throw error;
    return data || {};
  }

  function payloadFromForm(f, view) {
    const base = {
      set_code: f.set.toLowerCase(), number: f.number, lang: f.lang, foil: f.foil,
      quantity: f.qty, price: f.price, note: (f.note || "").trim(),
    };
    if (view === "sell") base.seller_id = uid;
    else { base.buyer_id = uid; base.must = !!f.must; }
    return base;
  }

  async function saveCard(form, view) {
    const c = await MTGSupabase.getClient();
    const table = view === "want" ? "wants" : "inventory";
    const ownerKey = view === "want" ? "buyer_id" : "seller_id";
    const payload = payloadFromForm(form, view);
    if (form.id) {
      // .eq(ownerKey, uid) 防御纵深：即便 RLS 被误改，也只改自己的行
      const { error } = await c.from(table).update(payload).eq("id", form.id).eq(ownerKey, uid);
      if (error) throw error;
    } else {
      const { error } = await c.from(table).insert(payload);
      if (error) throw error;
    }
  }

  async function deleteCard(id, view) {
    const c = await MTGSupabase.getClient();
    const table = view === "want" ? "wants" : "inventory";
    const ownerKey = view === "want" ? "buyer_id" : "seller_id";
    const { error } = await c.from(table).delete().eq("id", id).eq(ownerKey, uid);
    if (error) throw error;
  }

  async function bulkUpsert(rows, view) {
    const c = await MTGSupabase.getClient();
    const table = view === "want" ? "wants" : "inventory";
    const ownerKey = view === "want" ? "buyer_id" : "seller_id";
    // 批量/导入：强制 owner = 当前登录用户（parseLine 不返回 owner），
    // 忽略文件里的 # seller/buyer 头；note strip 归一化与 build 端 note_hash 对齐。
    const payload = rows.map((r) => ({ ...r, [ownerKey]: uid, note: (r.note || "").trim() }));
    // onConflict 列必须与 DB unique index 完全一致（见 SUPABASE_MIGRATION_PLAN.md 第 4 节
    // inventory_uniq / wants_uniq），否则 upsert 走不到合并、直接报唯一约束冲突。改 index 时同步。
    const conflict = view === "want"
      ? "buyer_id,set_code,number,lang,foil,must,price,note"
      : "seller_id,set_code,number,lang,foil,price,note";
    const { error } = await c.from(table).upsert(payload, { onConflict: conflict });
    if (error) throw error;
  }

  // 60s 前端节流（文档第 8 节）：成功触发后倒计时禁用按钮，防连点排队多个 workflow
  // （workflow concurrency cancel-in-progress=false，多点只会排队白跑）
  let publishCooldownUntil = 0;
  let cooldownTimer = null;

  function setPublishCooldown(seconds) {
    publishCooldownUntil = Date.now() + seconds * 1000;
    clearInterval(cooldownTimer);
    const btn = $("#publish-btn");
    const tick = () => {
      const remain = Math.ceil((publishCooldownUntil - Date.now()) / 1000);
      if (!btn) return;
      if (remain <= 0) {
        clearInterval(cooldownTimer);
        updatePublishGuard(); // 到期恢复：按 profile + 已过冷却统一算（不硬写 disabled=false，避免与 guard 抢状态）
        return;
      }
      btn.disabled = true;
      btn.textContent = `发布(${remain}s)`;
    };
    tick();
    cooldownTimer = setInterval(tick, 1000);
  }

  async function publish() {
    // 防御：按钮被 guard 禁用时点不到，但防控制台/竞态直接调 publish
    if (!profileIsComplete(profile)) {
      showToast("请先在「资料」补全昵称/城市/联系");
      return;
    }
    const now = Date.now();
    if (now < publishCooldownUntil) {
      showToast(`请稍候，${Math.ceil((publishCooldownUntil - now) / 1000)}s 后可再次发布`);
      return;
    }
    const session = await MTGSupabase.getSession();
    if (!session) { showToast("未登录"); return; }
    const btn = $("#publish-btn");
    if (btn) { btn.disabled = true; btn.textContent = "发布中…"; }
    try {
      const r = await fetch(`${MTGSupabase.site.supabase_url}/functions/v1/publish`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.access_token}`, "Content-Type": "application/json" },
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.error || `HTTP ${r.status}`);
      }
      showToast("已触发发布，约 1 分钟后站点更新");
      setPublishCooldown(60); // 成功才节流，接管按钮（不走 catch 的恢复）
      return;
    } catch (e) {
      showToast("发布失败：" + e.message);
      updatePublishGuard(); // 失败恢复统一走 guard（未成功不进 cooldown，disabled=!ok；与成功/到期路径一致）
    }
  }

  // ---------- 视图切换 ----------
  async function setView(view) {
    if (view !== "sell" && view !== "want") return;
    state.view = view;
    state.query = ""; state.seller = "all"; state.city = "all"; state.lang = "all";
    state.foil = "all"; state.kind = "all"; state.type = "all"; state.cmc = "all";
    state.visibleCount = PAGE_SIZE;
    const search = $("#search"); if (search) search.value = "";
    document.querySelectorAll(".view-tab").forEach((b) => {
      const on = b.dataset.view === view;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.setAttribute("tabindex", on ? "0" : "-1");
    });
    try {
      const rows = view === "sell" ? await loadInventory() : await loadWants();
      const cards = rows.map((r) => rowToCard(r, view));
      if (view === "sell") state.cards = cards; else state.wants = cards;
    } catch (e) {
      showToast("加载失败：" + e.message);
      if (view === "sell") state.cards = []; else state.wants = [];
    }
    // want-only 字段显隐
    document.querySelectorAll(".want-only").forEach((el) => {
      el.style.display = view === "want" ? "" : "none";
    });
    renderAdminMeta();
    populateFilters();
    renderGrid();
  }

  function renderAdminMeta() {
    const list = state.view === "want" ? state.wants : state.cards;
    $("#total-kinds").textContent = String(list.length);
    $("#total-qty").textContent = String(list.reduce((s, c) => s + (c.quantity || 0), 0));
    const kindsLabel = $("#stat-kinds-label");
    const qtyLabel = $("#stat-qty-label");
    if (kindsLabel) kindsLabel.textContent = state.view === "want" ? "条目" : "种类";
    if (qtyLabel) qtyLabel.textContent = "张数";
    const search = $("#search");
    if (search) search.placeholder = state.view === "want" ? "搜索牌名 / 备注…" : "搜索牌名 / 系列…";
  }

  // ---------- 表单 ----------
  function openForm(view, card) {
    const isWant = view === "want";
    $("#form-title").textContent = card ? "编辑" : "添加";
    $("#f-id").value = card ? card.id : "";
    $("#f-set").value = card ? card.set_code : "";
    $("#f-number").value = card ? card.number : "";
    const langTok = card ? ({ en: "e", zhs: "z", ja: "j", other: "o" }[card.lang] || "e") : "e";
    $("#f-lang").value = langTok;
    $("#f-foil").value = card && card.foil ? "1" : "0";
    $("#f-qty").value = card ? card.quantity : 1;
    $("#f-price").value = card ? Number(card.price) : 0;
    $("#f-must").value = card && card.must ? "1" : "0";
    $("#f-note").value = card ? (card.note || "") : "";
    $("#form-hint").textContent = "";
    $("#form-preview").hidden = true;
    showModal("form-modal");
    schedulePreview();
  }

  function formToObj() {
    return {
      id: $("#f-id").value || null,
      set: $("#f-set").value.trim(), number: $("#f-number").value.trim(),
      lang: tokToLang($("#f-lang").value), foil: $("#f-foil").value === "1",
      qty: normQty($("#f-qty").value), price: normPrice($("#f-price").value || "0"),
      must: $("#f-must").value === "1", note: $("#f-note").value,
    };
  }

  async function submitForm() {
    const view = state.view;
    let form;
    try { form = formToObj(); }
    catch (e) { $("#form-hint").textContent = e.message; return; }
    if (!form.set || !form.number) { $("#form-hint").textContent = "系列和编号必填"; return; }
    $("#form-submit").disabled = true;
    try {
      await saveCard(form, view);
      hideModal("form-modal");
      showToast(form.id ? "已更新" : "已添加");
      await setView(view);
    } catch (e) {
      $("#form-hint").textContent = "保存失败：" + e.message;
    } finally {
      $("#form-submit").disabled = false;
    }
  }

  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(previewCard, 400);
  }
  async function previewCard() {
    const set = $("#f-set").value.trim().toLowerCase();
    const number = $("#f-number").value.trim();
    const lang = tokToLang($("#f-lang").value);
    if (!set || !number) { $("#form-preview").hidden = true; return; }
    const slang = SCRYFALL_LANG[lang] || "en";
    try {
      const r = await fetch(`https://api.scryfall.io/cards/${encodeURIComponent(set)}/${encodeURIComponent(number)}/${slang}`);
      if (!r.ok) { $("#form-preview").hidden = true; return; }
      const j = await r.json();
      const img = (j.image_uris && (j.image_uris.normal || j.image_uris.small)) || "";
      if (img) {
        $("#form-preview-img").src = img;
        $("#form-preview-name").textContent = j.name || "";
        $("#form-preview").hidden = false;
      } else {
        $("#form-preview").hidden = true;
      }
    } catch {
      $("#form-preview").hidden = true;
    }
  }

  // ---------- 批量 / 导入 ----------
  async function submitBatch() {
    const text = $("#batch-text").value;
    const { rows, errors } = parseText(text, state.view);
    if (errors.length) { showToast(`解析失败 ${errors.length} 行：${errors[0]}`); return; }
    if (!rows.length) { showToast("无有效行"); return; }
    $("#batch-submit").disabled = true;
    try {
      await bulkUpsert(rows, state.view);
      hideModal("batch-modal");
      showToast(`已导入 ${rows.length} 条`);
      await setView(state.view);
    } catch (e) {
      showToast("导入失败：" + e.message);
    } finally {
      $("#batch-submit").disabled = false;
    }
  }

  async function submitImport(file) {
    const text = await file.text();
    const { rows, errors } = parseText(text, state.view);
    if (errors.length) { showToast(`解析失败 ${errors.length} 行：${errors[0]}`); return; }
    if (!rows.length) { showToast("文件无有效行"); return; }
    try {
      await bulkUpsert(rows, state.view);
      hideModal("import-modal");
      showToast(`已导入 ${rows.length} 条`);
      await setView(state.view);
    } catch (e) {
      showToast("导入失败：" + e.message);
    }
  }

  // ---------- 模态/提示（复用 mtg-ui 的 showToast / setScrollLock / syncInert）----------
  function showModal(id) {
    const m = $("#" + id);
    m.classList.add("open"); m.setAttribute("aria-hidden", "false");
    if (typeof setScrollLock === "function") setScrollLock(true);
    if (typeof syncInert === "function") syncInert();
  }
  function hideModal(id) {
    const m = $("#" + id);
    m.classList.remove("open"); m.setAttribute("aria-hidden", "true");
    if (typeof setScrollLock === "function") setScrollLock(false);
    if (typeof syncInert === "function") syncInert();
  }
  function anyModalOpen() {
    return !!document.querySelector(".modal.open");
  }

  // ---------- 事件 ----------
  function bindEvents() {
    $("#view-tabs")?.addEventListener("click", (e) => {
      const t = e.target.closest(".view-tab"); if (t) setView(t.dataset.view);
    });
    let searchTimer = null;
    $("#search")?.addEventListener("input", (e) => {
      state.query = e.target.value; state.visibleCount = PAGE_SIZE;
      clearTimeout(searchTimer); searchTimer = setTimeout(renderGrid, 150);
    });
    $("#add-btn")?.addEventListener("click", () => openForm(state.view, null));
    $("#batch-btn")?.addEventListener("click", () => {
      $("#batch-help").textContent = state.view === "want" ? WANTS_FMT : INVENTORY_FMT;
      $("#batch-text").value = ""; showModal("batch-modal");
    });
    $("#import-btn")?.addEventListener("click", () => {
      $("#import-help").textContent = state.view === "want" ? WANTS_FMT : INVENTORY_FMT;
      $("#import-file").value = ""; showModal("import-modal");
    });

    $("#grid")?.addEventListener("click", (e) => {
      if (e.target.closest("#load-more")) { if (typeof loadMore === "function") loadMore(); return; }
      const btn = e.target.closest("[data-act]");
      if (!btn) return;
      const id = btn.dataset.id;
      const list = state.view === "want" ? state.wants : state.cards;
      const card = list.find((c) => c.id === id);
      if (!card) return;
      if (btn.dataset.act === "edit") openForm(state.view, card._row);
      else if (btn.dataset.act === "del") {
        if (!confirm("删除该条？")) return;
        deleteCard(id, state.view).then(() => {
          showToast("已删除"); setView(state.view);
        }).catch((err) => showToast("删除失败：" + err.message));
      }
    });

    $("#card-form")?.addEventListener("submit", (e) => { e.preventDefault(); submitForm(); });
    $("#form-cancel")?.addEventListener("click", () => hideModal("form-modal"));
    $("#form-close")?.addEventListener("click", () => hideModal("form-modal"));
    $("#form-backdrop")?.addEventListener("click", () => hideModal("form-modal"));
    ["f-set", "f-number", "f-lang"].forEach((id) => {
      $("#" + id)?.addEventListener("input", schedulePreview);
    });

    $("#batch-submit")?.addEventListener("click", submitBatch);
    $("#batch-cancel")?.addEventListener("click", () => hideModal("batch-modal"));
    $("#batch-close")?.addEventListener("click", () => hideModal("batch-modal"));
    $("#batch-backdrop")?.addEventListener("click", () => hideModal("batch-modal"));

    $("#import-submit")?.addEventListener("click", () => {
      const f = $("#import-file").files[0];
      if (!f) { showToast("请先选择文件"); return; }
      submitImport(f);
    });
    $("#import-cancel")?.addEventListener("click", () => hideModal("import-modal"));
    $("#import-close")?.addEventListener("click", () => hideModal("import-modal"));
    $("#import-backdrop")?.addEventListener("click", () => hideModal("import-modal"));

    $("#publish-btn")?.addEventListener("click", publish);
    $("#profile-btn")?.addEventListener("click", openProfileModal);
    $("#profile-form")?.addEventListener("submit", (e) => { e.preventDefault(); saveProfile(); });
    $("#profile-cancel")?.addEventListener("click", () => hideModal("profile-modal"));
    $("#profile-close")?.addEventListener("click", () => hideModal("profile-modal"));
    $("#profile-backdrop")?.addEventListener("click", () => hideModal("profile-modal"));
    $("#signout-btn")?.addEventListener("click", async () => {
      await MTGSupabase.signOut(); window.location.href = "/";
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && anyModalOpen()) {
        document.querySelectorAll(".modal.open").forEach((m) => hideModal(m.id));
      }
    });
  }

  // ---------- 个人资料 ----------
  function profileIsComplete(p) {
    return !!p && ["seller_name", "city", "contact"].every((f) => (p[f] || "").trim());
  }

  function updatePublishGuard() {
    const btn = $("#publish-btn");
    const warn = $("#profile-warn");
    const ok = profileIsComplete(profile);
    const cooling = Date.now() < publishCooldownUntil;
    if (btn) {
      // 感知 cooldown：冷却中也保持 disabled（冷却 textContent 由 setPublishCooldown 的 tick 管）
      btn.disabled = !ok || cooling;
      btn.title = ok ? "" : "请先在「资料」补全昵称/城市/联系，否则发布后库存不展示";
      if (!cooling) btn.textContent = "立即发布";
    }
    if (warn) {
      if (ok) {
        warn.hidden = true;
      } else {
        const missing = ["seller_name", "city", "contact"].filter(
          (f) => !((profile && profile[f]) || "").trim()
        );
        warn.hidden = false;
        warn.textContent = `⚠ 资料缺 ${missing.join(" / ")}，发布被禁用（发布后库存会被 export 跳过、站点变空）。点右上「资料」补全。`;
      }
    }
  }

  function openProfileModal() {
    $("#p-seller_name").value = (profile && profile.seller_name) || "";
    $("#p-city").value = (profile && profile.city) || "";
    $("#p-contact").value = (profile && profile.contact) || "";
    $("#p-hint").textContent = "三项都必填，否则发布的库存/求购会被 export 整批跳过。";
    showModal("profile-modal");
  }

  async function saveProfile() {
    const payload = {
      seller_name: $("#p-seller_name").value.trim(),
      city: $("#p-city").value.trim(),
      contact: $("#p-contact").value.trim(),
    };
    const hint = $("#p-hint");
    if (!payload.seller_name || !payload.city || !payload.contact) {
      if (hint) hint.textContent = "三项都必填";
      return;
    }
    const submit = $("#profile-submit");
    if (submit) submit.disabled = true;
    try {
      const c = await MTGSupabase.getClient();
      const { error } = await c.from("profiles").update(payload).eq("id", uid);
      if (error) {
        const msg = /duplicate|unique|23505/i.test(error.message)
          ? "昵称已被占用"
          : "保存失败：" + error.message;
        if (hint) hint.textContent = msg;
        return;
      }
      profile = { ...(profile || {}), ...payload };
      hideModal("profile-modal");
      showToast("资料已保存");
      updatePublishGuard();
    } catch (e) {
      if (hint) hint.textContent = "保存失败：" + e.message;
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  // ---------- 入口 ----------
  async function main() {
    // auth 门禁：无 session 跳回主站登录
    const user = await MTGSupabase.requireUser();
    if (!user) return;
    uid = user.id;
    $("#admin-email").textContent = user.email || "";

    buildDisplayIndex();
    try {
      profile = await loadProfile();
    } catch (e) {
      showToast("读取 profile 失败：" + e.message);
      profile = {};
    }
    updatePublishGuard(); // profile 不全则禁用发布按钮 + 显警告（带「资料」补全入口）

    // override 全局 cardHtml（admin 版）
    cardHtml = adminCardHtml;
    // 注册 decorateCard：渲染后给 join 不到图的新加拉 Scryfall 图 + 名
    window.decorateCard = adminDecorateCard;

    if (typeof mountFilters === "function") mountFilters();
    bindEvents();
    await setView("sell");
  }

  main().catch((err) => {
    console.error(err);
    const el = $("#empty");
    if (el) { el.hidden = false; el.textContent = "加载失败：" + (err && err.message ? err.message : err); }
  });
})();
