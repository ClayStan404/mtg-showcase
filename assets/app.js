/* app.js -- 主站入口（shell）：cart/意向清单、详情弹窗、数据加载、view 切换、事件绑定。
 * 展示/筛选/分页逻辑在 mtg-ui.js（先于本文件加载，共享全局）。
 */
// v2：card_id 加了 price + note_hash（见 build_data.py card_id），v1 的清单 id 全成幽灵，故 bump key 清空旧清单
const CART_KEY = "mtg-wishlist-v2";

function loadCart() {
  try {
    const raw = localStorage.getItem(CART_KEY);
    if (!raw) return {};
    const data = JSON.parse(raw);
    if (!data || typeof data !== "object") return {};
    const clean = {};
    for (const [k, v] of Object.entries(data)) {
      // 仅保留正整数，防止 localStorage 损坏导致 cartCount 拼接成字符串
      if (typeof v === "number" && v > 0) clean[k] = Math.floor(v);
    }
    return clean;
  } catch {
    return {};
  }
}

function saveCart() {
  try {
    localStorage.setItem(CART_KEY, JSON.stringify(state.cart));
  } catch {
    // 配额满或隐私模式，清单无法持久化
    showToast("清单保存失败（本地存储已满或被禁用）");
  }
}

function cartCount() {
  return Object.values(state.cart).reduce((s, n) => s + (n || 0), 0);
}

function cartKinds() {
  return Object.keys(state.cart).filter((id) => state.cart[id] > 0).length;
}

function inCart(id) {
  return (state.cart[id] || 0) > 0;
}

function maxWant(card) {
  return Math.max(1, Number(card.quantity) || 1);
}

function addToCart(cardId, delta = 1) {
  const card = state.cardIndex?.get(cardId);
  if (!card) return;
  const max = maxWant(card);
  const cur = state.cart[cardId] || 0;
  if (delta > 0 && cur >= max) {
    showToast("已达库存上限");
    return;
  }
  const next = Math.min(max, cur + delta);
  if (next <= 0) {
    delete state.cart[cardId];
  } else {
    state.cart[cardId] = next;
  }
  saveCart();
  renderCartList();
  // 刷新当前可见卡片按钮状态
  refreshCardButton(cardId);
}

function refreshCardButton(cardId) {
  const esc =
    window.CSS && typeof CSS.escape === "function"
      ? CSS.escape(cardId)
      : String(cardId).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  document.querySelectorAll(`.card-add[data-id="${esc}"]`).forEach((btn) => {
    const on = inCart(cardId);
    btn.classList.toggle("is-in", on);
    btn.textContent = on ? "已加" : "加入";
    btn.setAttribute("aria-label", on ? "已在清单" : "加入意向清单");
  });
  const modalAdd = $("#modal-add");
  if (modalAdd && state.modalCardId === cardId) {
    modalAdd.classList.toggle("is-in", inCart(cardId));
    modalAdd.textContent = inCart(cardId) ? "已在清单中 · 再加一张" : "加入意向清单";
  }
}

function setCartQty(cardId, qty) {
  const card = state.cardIndex?.get(cardId);
  if (!card) return;
  const max = maxWant(card);
  const next = Math.max(0, Math.min(max, qty));
  if (next <= 0) delete state.cart[cardId];
  else state.cart[cardId] = next;
  saveCart();
  renderCartList();
  refreshCardButton(cardId);
}

function clearCart() {
  state.cart = {};
  saveCart();
  renderCartList();
  const visible = (state._filtered || activeList()).slice(0, state.visibleCount);
  for (const c of visible) refreshCardButton(c.id);
  showToast("清单已清空");
}

function updateCartChrome() {
  const n = cartCount();
  const badge = $("#cart-fab-count");
  if (badge) {
    badge.hidden = n <= 0;
    badge.textContent = String(n);
  }
  const kinds = $("#cart-kinds");
  const units = $("#cart-units");
  if (kinds) kinds.textContent = String(cartKinds());
  if (units) units.textContent = String(n);
  const footer = $("#cart-footer");
  if (footer) footer.hidden = n <= 0;
}

function openCart() {
  closeAllDropdowns();
  closeModal();
  _lastFocus = document.activeElement;
  const cart = $("#cart");
  cart.classList.add("open");
  cart.setAttribute("aria-hidden", "false");
  state.cartOpen = true;
  setScrollLock(true);
  syncInert();
  renderCartList();
  updateCartChrome();
  $("#cart-close")?.focus();
}

function closeCart() {
  const cart = $("#cart");
  cart.classList.remove("open");
  cart.classList.remove("shot-mode");
  cart.setAttribute("aria-hidden", "true");
  state.cartOpen = false;
  state.shotMode = false;
  const btn = $("#cart-shot-mode");
  if (btn) btn.textContent = "截图模式";
  if (!anyOverlayOpen()) {
    setScrollLock(false);
    syncInert();
    _lastFocus?.focus?.({ preventScroll: true });
    _lastFocus = null;
  } else {
    syncInert();
  }
}

function toggleShotMode() {
  state.shotMode = !state.shotMode;
  $("#cart").classList.toggle("shot-mode", state.shotMode);
  const btn = $("#cart-shot-mode");
  if (btn) btn.textContent = state.shotMode ? "退出截图模式" : "截图模式";
  if (state.shotMode) showToast("可直接截取清单区域发给卖家");
}

function cartLines() {
  const ids = Object.keys(state.cart).filter((id) => state.cart[id] > 0);
  const items = ids
    .map((id) => {
      const card = state.cardIndex?.get(id);
      if (!card) return null;
      return { card, want: state.cart[id] };
    })
    .filter(Boolean);

  // 按出售人分组
  const groups = new Map();
  for (const it of items) {
    const key = it.card.seller || "未知出售人";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(it);
  }
  return { items, groups };
}

function buildCartText() {
  const { groups, items } = cartLines();
  if (!items.length) return "";
  const lines = ["【万智牌意向清单】", `共 ${cartKinds()} 种 / ${cartCount()} 张`, ""];
  for (const [seller, list] of groups) {
    const city = list[0]?.card.city || "";
    const contact = list[0]?.card.contact || "";
    lines.push(`■ ${seller}${city ? `（${city}）` : ""}`);
    if (contact) lines.push(`  联系：${contact}`);
    for (const { card, want } of list) {
      const name = displayName(card);
      const set = `${(card.set || "").toUpperCase()} #${card.number}`;
      const lang = card.lang_label || card.lang || "";
      const foil = card.foil ? " 闪" : "";
      lines.push(`  - ${name} · ${set} · ${lang}${foil} · ×${want}`);
    }
    lines.push("");
  }
  lines.push("（来自 claystan.cc 展示站，仅作沟通参考）");
  return lines.join("\n");
}

async function copyCartText() {
  const text = buildCartText();
  if (!text) {
    showToast("清单是空的");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    showToast("清单文本已复制");
  } catch {
    // fallback
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      showToast("清单文本已复制");
    } catch {
      showToast("复制失败，请手动选择文本");
    }
    ta.remove();
  }
}

function renderCartList() {
  const empty = $("#cart-empty");
  const list = $("#cart-list");
  if (!list) return;
  const { groups, items } = cartLines();
  if (!items.length) {
    if (empty) empty.hidden = false;
    list.innerHTML = "";
    updateCartChrome();
    return;
  }
  if (empty) empty.hidden = true;

  let html = "";
  for (const [seller, group] of groups) {
    const city = group[0]?.card.city || "";
    const contact = (group[0]?.card.contact || "").trim();
    html += `<section class="cart-group">
      <header class="cart-group-head">
        <h3 class="cart-group-title">${escapeHtml(seller)}${city ? ` · ${escapeHtml(city)}` : ""}</h3>
        ${
          contact
            ? `<p class="cart-group-contact"><span class="cart-contact-label">联系</span>${escapeHtml(contact)}</p>`
            : `<p class="cart-group-contact muted">暂无联系方式，见卡牌详情</p>`
        }
      </header>`;
    for (const { card, want } of group) {
      const img = card.image?.normal || card.image?.small || PLACEHOLDER_IMG;
      html += `
        <article class="cart-item" data-id="${escapeHtml(card.id)}">
          <img src="${escapeHtml(img)}" alt="" loading="lazy" decoding="async" />
          <div class="cart-item-main">
            <p class="cart-item-name">${escapeHtml(displayName(card))}</p>
            <p class="cart-item-meta">
              ${escapeHtml((card.set || "").toUpperCase())} #${escapeHtml(card.number)}
              · ${escapeHtml(card.lang_label || card.lang || "")}
              ${card.foil ? " · 闪" : ""}
            </p>
          </div>
          <div class="cart-item-actions">
            <div class="cart-qty">
              <button type="button" data-act="dec" data-id="${escapeHtml(card.id)}" aria-label="减少 ${escapeHtml(displayName(card))} 数量">−</button>
              <span>${want}</span>
              <button type="button" data-act="inc" data-id="${escapeHtml(card.id)}" aria-label="增加 ${escapeHtml(displayName(card))} 数量">+</button>
            </div>
            <button type="button" class="btn btn-danger-ghost btn-sm" data-act="rm" data-id="${escapeHtml(card.id)}">移除</button>
          </div>
        </article>`;
    }
    html += `</section>`;
  }
  list.innerHTML = html;
  bindImgErrors(list);
  updateCartChrome();
}

function openModal(card) {
  closeAllDropdowns();
  const modal = $("#modal");
  state.modalCardId = card.id;
  const isWant = state.view === "want";
  const must = isWant && (card.must === true || card.kind === "exact");
  const flex = isWant && (card.must === false || card.kind === "flex");

  const modalImg = $("#modal-img");
  if (modalImg) {
    // 重置 onerror 可能设置的 visibility:hidden 与 .img-failed，否则切换卡牌后状态残留
    modalImg.style.visibility = "";
    modalImg.parentElement?.classList.remove("img-failed");
    modalImg.alt = displayName(card);
    const realSrc = card.image?.normal || card.image?.large || "";
    // 先用透明占位替换旧图，预加载新图完成后再设 src，
    // 避免切换卡牌时短暂显示上一张卡图
    modalImg.src = PLACEHOLDER_IMG;
    const markImgFailed = () => {
      if (state.modalCardId !== card.id) return;
      modalImg.style.visibility = "hidden";
      // .modal-art.img-failed::after 会显示“图加载失败”，否则用户只看到空白
      modalImg.parentElement?.classList.add("img-failed");
    };
    if (realSrc) {
      const preload = new Image();
      preload.onload = () => {
        if (state.modalCardId === card.id) modalImg.src = realSrc;
      };
      preload.onerror = markImgFailed;
      preload.src = realSrc;
    } else {
      // 无图片 URL（数据缺图），直接标记失败
      markImgFailed();
    }
  }
  $("#modal-title").textContent = displayName(card);
  $("#modal-en").textContent = secondaryName(card);
  $("#modal-en").hidden = !secondaryName(card);

  const typeShort = typeLabelShort(card);
  const mana = formatManaCost(card);
  const imgLang = imageLangLabel(card);
  const cardPrice = Number(card.price) || 0;
  const priceTag = cardPrice > 0 ? `<span class="tag">¥${escapeHtml(cardPrice.toFixed(2))}</span>` : "";
  $("#modal-tags").innerHTML = [
    isWant
      ? `<span class="tag">${must ? "必须此版" : "可替其他版"}</span>`
      : `<span class="tag">${escapeHtml(card.lang_label || card.lang)}</span>`,
    imgLang ? `<span class="tag">图:${escapeHtml(imgLang)}</span>` : "",
    card.foil ? '<span class="tag foil">闪卡 FOIL</span>' : "",
    typeShort ? `<span class="tag">${escapeHtml(typeShort)}</span>` : "",
    mana ? `<span class="tag">${escapeHtml(mana)}</span>` : "",
    `<span class="tag">×${escapeHtml(String(card.quantity))}</span>`,
    priceTag,
    card.city ? `<span class="tag">${escapeHtml(card.city)}</span>` : "",
  ].join("");

  const personLabel = $("#modal-person-label");
  if (personLabel) personLabel.textContent = isWant ? "买家" : "出售人";
  $("#modal-seller").textContent = (isWant ? card.buyer : card.seller) || "—";
  $("#modal-city").textContent = card.city || "—";
  $("#modal-contact").textContent = card.contact || "—";

  $("#modal-set-label").textContent = "系列";
  $("#modal-set").textContent = `${card.set_name || ""} (${(card.set || "").toUpperCase()})`;
  $("#modal-number-label").textContent = "编号";
  $("#modal-number").textContent = card.number || "—";
  $("#modal-type").textContent = card.type_line || card.type_line_en || "—";
  const manaDd = $("#modal-mana");
  if (manaDd) {
    const cmcNum = Number(card.cmc);
    const cmcPart = Number.isFinite(cmcNum)
      ? `CMC ${cmcNum}`
      : "";
    if (mana && cmcPart) manaDd.textContent = `${mana} · ${cmcPart}`;
    else if (mana) manaDd.textContent = mana;
    else if (cmcPart) manaDd.textContent = cmcPart;
    else manaDd.textContent = "—";
  }
  let face = card.text || "（无牌面文字）";
  if (isWant && flex) {
    face = `【可替】参考此印刷，其他系列/语言/闪也可。\n\n${face}`;
  } else if (isWant && must) {
    face = `【必须】只要此印刷（系列+编号+语言+闪）。\n\n${face}`;
  }
  $("#modal-text").textContent = face;
  const noteLabel = $("#modal-note-label");
  const noteDd = $("#modal-note");
  if (noteLabel && noteDd) {
    if (card.note) {
      noteLabel.hidden = false;
      noteDd.hidden = false;
      noteDd.textContent = card.note;
    } else {
      noteLabel.hidden = true;
      noteDd.hidden = true;
      noteDd.textContent = "";
    }
  }

  const link = $("#modal-scryfall");
  setHrefSafe(link, card.scryfall_uri);

  const modalAdd = $("#modal-add");
  if (modalAdd) {
    if (isWant) {
      modalAdd.hidden = true;
    } else {
      modalAdd.hidden = false;
      const on = inCart(card.id);
      modalAdd.classList.toggle("is-in", on);
      modalAdd.textContent = on ? "已在清单中 · 再加一张" : "加入意向清单";
    }
  }

  _lastFocus = document.activeElement;
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  setScrollLock(true);
  syncInert();
  const panel = modal.querySelector(".modal-panel");
  if (panel) panel.scrollTop = 0;
  $("#modal-close").focus({ preventScroll: true });
}

function closeModal() {
  const modal = $("#modal");
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  state.modalCardId = null;
  if (!anyOverlayOpen()) {
    setScrollLock(false);
    syncInert();
    _lastFocus?.focus?.({ preventScroll: true });
    _lastFocus = null;
  } else {
    syncInert();
  }
  syncScrim();
}

function renderSiteMeta() {
  const site = state.site || {};
  const isWant = state.view === "want";
  const baseTitle = site.title || "万智牌 Sales List";
  document.title = isWant ? `${baseTitle} · 求购` : baseTitle;
  $("#site-title").textContent = baseTitle;
  $("#site-subtitle").textContent = isWant
    ? "买家求购 · 卖家可按联系方式对接"
    : site.subtitle || "";

  const list = activeList();
  $("#total-kinds").textContent = String(list.length);
  $("#total-qty").textContent = String(list.reduce((sum, c) => sum + (c.quantity || 0), 0));
  const kindsLabel = $("#stat-kinds-label");
  const qtyLabel = $("#stat-qty-label");
  if (kindsLabel) kindsLabel.textContent = isWant ? "条目" : "种类";
  if (qtyLabel) qtyLabel.textContent = isWant ? "张数" : "张数";

  const fab = $("#cart-fab");
  if (fab) fab.hidden = isWant;

  const search = $("#search");
  if (search) {
    search.placeholder = isWant
      ? "搜索牌名 / 买家 / 备注…"
      : "搜索牌名 / 系列 / 出售人…";
  }

  const lastUpd = $("#last-updated");
  if (lastUpd) {
    if (state.generatedAt) {
      const d = new Date(state.generatedAt);
      lastUpd.textContent = `最后更新：${d.toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}`;
      lastUpd.hidden = false;
    } else {
      lastUpd.hidden = true;
    }
  }
}

function setView(view) {
  if (view !== "sell" && view !== "want") return;
  state.view = view;
  state.query = "";
  state.seller = "all";
  state.city = "all";
  state.lang = "all";
  state.foil = "all";
  state.kind = "all";
  state.type = "all";
  state.cmc = "all";
  state.filtersOpen = false;
  state.visibleCount = PAGE_SIZE;
  const search = $("#search");
  if (search) search.value = "";
  document.querySelectorAll(".view-tab").forEach((btn) => {
    const on = btn.dataset.view === view;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
    btn.setAttribute("tabindex", on ? "0" : "-1");
  });
  setFiltersOpen(false);
  // 切 Tab 后恢复工具栏：移动端可能在上一视图滚到底部被自动收起，
  // 切 Tab 不触发 scroll，不重置会导致搜索栏在新视图里持续不可见
  $("#toolbar")?.classList.remove("is-collapsed");
  closeModal();
  closeCart();
  renderSiteMeta();
  populateFilters();
  renderGrid();
}

function bindEvents() {
  state.cart = loadCart();

  $("#view-tabs")?.addEventListener("click", (e) => {
    const tab = e.target.closest(".view-tab");
    if (!tab) return;
    setView(tab.dataset.view);
  });

  $("#view-tabs")?.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const tabs = [...document.querySelectorAll(".view-tab")];
    const cur = tabs.findIndex((t) => t.getAttribute("tabindex") === "0");
    const next =
      e.key === "ArrowRight"
        ? (cur + 1) % tabs.length
        : (cur - 1 + tabs.length) % tabs.length;
    if (!tabs[next]) return;
    tabs[next].focus();
    setView(tabs[next].dataset.view);
    e.preventDefault();
  });

  let searchTimer = null;
  $("#search")?.addEventListener("input", (e) => {
    state.query = e.target.value;
    state.visibleCount = PAGE_SIZE;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderGrid, 150);
  });
  $("#search")?.addEventListener("focus", () => {
    $("#toolbar")?.classList.remove("is-collapsed");
  });

  $("#filter-toggle")?.addEventListener("click", (e) => {
    e.stopPropagation();
    setFiltersOpen(!state.filtersOpen);
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest(".dd") || e.target.closest("#dd-scrim") || e.target.closest(".dd-menu")) {
      return;
    }
    closeAllDropdowns();
    // 点筛选区外收起手机端筛选条（搜索框除外）
    if (
      isNarrow() &&
      state.filtersOpen &&
      !e.target.closest("#filters") &&
      !e.target.closest("#filter-toggle")
    ) {
      setFiltersOpen(false);
    }
  });

  const scrim = $("#dd-scrim");
  if (scrim) {
    scrim.addEventListener("click", () => closeAllDropdowns());
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeAllDropdowns();
      if (state.cartOpen) closeCart();
      else closeModal();
      return;
    }
    if (e.key === "Tab") {
      const container = state.cartOpen
        ? $("#cart-panel")
        : state.modalCardId
        ? document.querySelector(".modal-panel")
        : null;
      if (container) trapFocus(container, e);
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const openMenu =
        document.querySelector(".dd-menu.is-portal") ||
        document.querySelector(".dd.open .dd-menu");
      if (openMenu) {
        e.preventDefault();
        const opts = [...openMenu.querySelectorAll('[role="option"]')];
        if (!opts.length) return;
        const curIdx = opts.findIndex(
          (o) => o === document.activeElement || o.contains(document.activeElement)
        );
        const nextIdx =
          curIdx < 0 ? 0 : (curIdx + (e.key === "ArrowDown" ? 1 : -1) + opts.length) % opts.length;
        opts[nextIdx]?.focus();
      }
    }
  });

  $("#grid")?.addEventListener("click", (e) => {
    if (e.target.closest("#load-more")) {
      loadMore();
      return;
    }
    const addBtn = e.target.closest(".card-add");
    if (addBtn) {
      e.preventDefault();
      e.stopPropagation();
      const id = addBtn.dataset.id;
      const was = inCart(id);
      const before = cartCount();
      addToCart(id, 1);
      // 仅在清单确实变化时提示；达上限时 cartCount 不变，addToCart 内部已提示“已达库存上限”
      if (cartCount() > before) showToast(was ? "已更新清单" : "已加入意向清单");
      return;
    }
    const hit = e.target.closest(".card-hit");
    if (!hit) return;
    const card = activeList().find((c) => c.id === hit.dataset.id);
    if (card) openModal(card);
  });

  $("#modal-close")?.addEventListener("click", closeModal);
  $("#modal-backdrop")?.addEventListener("click", closeModal);
  $("#modal-add")?.addEventListener("click", () => {
    if (!state.modalCardId || state.view === "want") return;
    const was = inCart(state.modalCardId);
    addToCart(state.modalCardId, 1);
    if (!was && inCart(state.modalCardId)) showToast("已加入意向清单");
  });

  $("#cart-fab")?.addEventListener("click", openCart);
  $("#cart-close")?.addEventListener("click", closeCart);
  $("#cart-backdrop")?.addEventListener("click", closeCart);
  $("#cart-copy")?.addEventListener("click", copyCartText);
  $("#cart-clear")?.addEventListener("click", () => {
    if (!cartCount()) return;
    if (confirm("确定清空意向清单？")) clearCart();
  });
  $("#cart-shot-mode")?.addEventListener("click", toggleShotMode);

  $("#cart-list")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const id = btn.dataset.id;
    const act = btn.dataset.act;
    const cur = state.cart[id] || 0;
    if (act === "inc") addToCart(id, 1);
    else if (act === "dec") setCartQty(id, cur - 1);
    else if (act === "rm") setCartQty(id, 0);
  });

  const toolbar = $("#toolbar");
  const observer = new IntersectionObserver(
    ([entry]) => {
      toolbar.classList.toggle("is-stuck", entry.intersectionRatio < 1);
    },
    { threshold: [1], rootMargin: "-1px 0px 0px 0px" }
  );
  observer.observe(toolbar);

  // 滚动/旋转时关掉或重定位筛选菜单，避免悬空
  const reflowOrClose = () => {
    const open = document.querySelector(".dd.open");
    if (!open) return;
    portalMenuIfNeeded(open, true);
    const menu = findMenu(open.dataset.filter);
    if (menu?.classList.contains("is-portal")) {
      positionPortaledMenu(open, menu);
    }
  };
  window.addEventListener("resize", reflowOrClose, { passive: true });

  let lastScrollY = window.scrollY || 0;
  let scrollTicking = false;
  window.addEventListener(
    "scroll",
    (e) => {
      // capture 会收到所有可滚动元素的 scroll；菜单内部滑动不能关下拉
      if (state.anyDropdownOpen) {
        const t = e.target;
        const inMenu =
          t instanceof Element &&
          (t.classList.contains("dd-menu") || t.closest(".dd-menu"));
        if (!inMenu) closeAllDropdowns();
      }

      if (!isNarrow() || state.cartOpen || $("#modal")?.classList.contains("open")) return;
      if (scrollTicking) return;
      scrollTicking = true;
      requestAnimationFrame(() => {
        scrollTicking = false;
        const y = window.scrollY || 0;
        const bar = $("#toolbar");
        if (!bar) return;
        // 搜索聚焦或筛选展开时不自动隐藏
        const searchFocused = document.activeElement === $("#search");
        if (searchFocused || state.filtersOpen) {
          bar.classList.remove("is-collapsed");
          lastScrollY = y;
          return;
        }
        const delta = y - lastScrollY;
        if (y < 48) {
          bar.classList.remove("is-collapsed");
        } else if (delta > 6) {
          bar.classList.add("is-collapsed");
        } else if (delta < -6) {
          bar.classList.remove("is-collapsed");
        }
        lastScrollY = y;
      });
    },
    { passive: true, capture: true }
  );

  $("#modal-img")?.addEventListener("error", function () {
    onImgError(this);
  });

  updateCartChrome();
  updateFilterToggle();
}

function showLoadError(msg) {
  const el = $("#empty");
  if (!el) return;
  el.hidden = false;
  el.textContent = msg;
}

async function loadJsonFallback(urls, check) {
  let lastErr = null;
  for (const url of urls) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) {
        lastErr = new Error(`HTTP ${res.status} loading ${url}`);
        continue;
      }
      const data = await res.json();
      if (!check(data)) {
        lastErr = new Error(`${url} 格式无效`);
        continue;
      }
      return data;
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error("无法加载数据");
}

/**
 * Prefer live Storage snapshot (updated without full Pages deploy).
 * Fall back to inlined cards-data.js / local data/*.json if Storage is empty or fails.
 */
async function loadCatalog(kind) {
  const isSell = kind === "sell";
  const file = isSell ? "cards.json" : "wants.json";
  const listKey = isSell ? "cards" : "wants";
  const check = (d) => d && Array.isArray(d[listKey]);
  const bust = Date.now();
  const base =
    (window.MTGSupabase && typeof MTGSupabase.dataBaseUrl === "function" && MTGSupabase.dataBaseUrl()) ||
    "";
  const urls = [];
  if (base) urls.push(`${base}/${file}?v=${bust}`);
  urls.push(`data/${file}?v=${bust}`, `data/${file}`);

  try {
    return await loadJsonFallback(urls, check);
  } catch (liveErr) {
    const inline = isSell ? window.__MTG_DATA__ : window.__MTG_WANTS__;
    if (inline && Array.isArray(inline[listKey])) return inline;
    throw liveErr;
  }
}

async function loadData() {
  // 在售：Storage 快照优先，内联/本地兜底
  const sell = await loadCatalog("sell");

  // 求购（可选，失败则空列表）
  let wants = { wants: [] };
  try {
    wants = await loadCatalog("want");
  } catch {
    wants = { wants: [] };
  }

  return { sell, wants };
}

// ---------- 登录 / 管理入口（主站）----------
// 首屏用 localStorage 轻量探测 session（不加载 vendor，买家零成本）；点登录/登出才懒加载 supabase-js。
function showAuthArea(loggedIn, email) {
  const loginBtn = $("#login-btn");
  const emailEl = $("#auth-email");
  const adminLink = $("#admin-link");
  const logoutBtn = $("#logout-btn");
  if (loginBtn) loginBtn.hidden = loggedIn;
  if (emailEl) { emailEl.hidden = !loggedIn; if (loggedIn && email) emailEl.textContent = email; }
  if (adminLink) adminLink.hidden = !loggedIn;
  if (logoutBtn) logoutBtn.hidden = !loggedIn;
}

function openLoginModal() {
  const m = $("#login-modal");
  if (!m) return;
  $("#login-hint").textContent = "邀请制，无账号请联系管理员。";
  m.classList.add("open");
  m.setAttribute("aria-hidden", "false");
  setScrollLock(true);
  syncInert();
  $("#login-email")?.focus();
}

function closeLoginModal() {
  const m = $("#login-modal");
  if (!m || !m.classList.contains("open")) return;
  m.classList.remove("open");
  m.setAttribute("aria-hidden", "true");
  if (!anyOverlayOpen()) {
    setScrollLock(false);
    syncInert();
  }
}

function initAuth() {
  if (!window.MTGSupabase) return;
  showAuthArea(MTGSupabase.hasLocalSession(), "");

  $("#login-btn")?.addEventListener("click", openLoginModal);
  $("#login-close")?.addEventListener("click", closeLoginModal);
  $("#login-backdrop")?.addEventListener("click", closeLoginModal);
  $("#login-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = $("#login-email").value.trim();
    const password = $("#login-password").value;
    const submit = $("#login-submit");
    const hint = $("#login-hint");
    if (submit) submit.disabled = true;
    if (hint) hint.textContent = "登录中…";
    try {
      const c = await MTGSupabase.getClient(); // 此处懒加载 vendor（约 55KB gzip）
      const { data, error } = await c.auth.signInWithPassword({ email, password });
      if (error) throw error;
      showAuthArea(true, (data.user && data.user.email) || email);
      $("#login-password").value = "";
      closeLoginModal();
      showToast("已登录，点「管理」进入后台");
    } catch (err) {
      if (hint) hint.textContent = "登录失败：" + (err && err.message ? err.message : err);
    } finally {
      if (submit) submit.disabled = false;
    }
  });
  $("#logout-btn")?.addEventListener("click", async () => {
    try { await MTGSupabase.signOut(); } catch {}
    showAuthArea(false, "");
    showToast("已登出");
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("#login-modal")?.classList.contains("open")) closeLoginModal();
  });
}

async function main() {
  mountFilters();
  bindEvents();
  initAuth();
  const empty = $("#empty");
  if (empty) {
    empty.textContent = "加载中…";
    empty.hidden = false;
  }
  const data = await loadData();
  state.cards = data.sell.cards || [];
  state.cardIndex = new Map(state.cards.map((c) => [c.id, c]));
  state.site = data.sell.site || data.wants.site || {};
  state.wants = data.wants.wants || [];
  state.generatedAt = data.sell.generated_at || data.wants.generated_at || "";
  // 清理清单里已不存在的卡，并按当前库存上限 clamp 数量
  for (const id of Object.keys(state.cart)) {
    const card = state.cardIndex?.get(id);
    if (!card) delete state.cart[id];
    else state.cart[id] = Math.min(state.cart[id], maxWant(card));
  }
  saveCart();
  renderSiteMeta();
  populateFilters();
  renderGrid();
  updateCartChrome();
}

main().catch((err) => {
  console.error(err);
  const detail = err && err.message ? err.message : String(err);
  showLoadError(`加载失败：${detail}。请检查网络后刷新页面，或稍后重试。`);
});

