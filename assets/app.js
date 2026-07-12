/* global fetch, document, window */

const CART_KEY = "mtg-wishlist-v1";

const state = {
  view: "sell", // sell | want
  cards: [],
  wants: [],
  site: null,
  query: "",
  lang: "all",
  foil: "all",
  seller: "all", // sell: 出售人；want: 买家 id
  city: "all",
  kind: "all", // want only: printing | any
  /** @type {Record<string, number>} cardId -> want qty */
  cart: {},
  cartOpen: false,
  shotMode: false,
  modalCardId: null,
  filtersOpen: false,
};

function loadCart() {
  try {
    const raw = localStorage.getItem(CART_KEY);
    if (!raw) return {};
    const data = JSON.parse(raw);
    return data && typeof data === "object" ? data : {};
  } catch {
    return {};
  }
}

function saveCart() {
  try {
    localStorage.setItem(CART_KEY, JSON.stringify(state.cart));
  } catch {
    /* ignore quota */
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
  const card = state.cards.find((c) => c.id === cardId);
  if (!card) return;
  const max = maxWant(card);
  const cur = state.cart[cardId] || 0;
  const next = Math.min(max, cur + delta);
  if (next <= 0) {
    delete state.cart[cardId];
  } else {
    state.cart[cardId] = next;
  }
  saveCart();
  updateCartChrome();
  renderCartList();
  // 刷新当前可见卡片按钮状态
  const esc =
    window.CSS && typeof CSS.escape === "function"
      ? CSS.escape(cardId)
      : String(cardId).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  document.querySelectorAll(`.card-add[data-id="${esc}"]`).forEach((btn) => {
    const on = inCart(cardId);
    btn.classList.toggle("is-in", on);
    btn.textContent = on ? "已加" : "加入";
  });
  const modalAdd = $("#modal-add");
  if (modalAdd && state.modalCardId === cardId) {
    modalAdd.classList.toggle("is-in", inCart(cardId));
    modalAdd.textContent = inCart(cardId) ? "已在清单中 · 再加一张" : "加入意向清单";
  }
}

function setCartQty(cardId, qty) {
  const card = state.cards.find((c) => c.id === cardId);
  if (!card) return;
  const max = maxWant(card);
  const next = Math.max(0, Math.min(max, qty));
  if (next <= 0) delete state.cart[cardId];
  else state.cart[cardId] = next;
  saveCart();
  updateCartChrome();
  renderCartList();
  renderGrid();
}

function clearCart() {
  state.cart = {};
  saveCart();
  updateCartChrome();
  renderCartList();
  renderGrid();
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

function showToast(msg) {
  const el = $("#toast");
  if (!el) return;
  el.hidden = false;
  el.textContent = msg;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    el.hidden = true;
  }, 1800);
}

function openCart() {
  closeAllDropdowns();
  closeModal();
  const cart = $("#cart");
  cart.classList.add("open");
  cart.setAttribute("aria-hidden", "false");
  state.cartOpen = true;
  setScrollLock(true);
  renderCartList();
  updateCartChrome();
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
  setScrollLock(false);
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
      const card = state.cards.find((c) => c.id === id);
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
      const img = card.image?.small || card.image?.normal || "";
      html += `
        <article class="cart-item" data-id="${escapeAttr(card.id)}">
          <img src="${escapeAttr(img)}" alt="" loading="lazy" decoding="async" />
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
              <button type="button" data-act="dec" data-id="${escapeAttr(card.id)}" aria-label="减少">−</button>
              <span>${want}</span>
              <button type="button" data-act="inc" data-id="${escapeAttr(card.id)}" aria-label="增加">+</button>
            </div>
            <button type="button" class="btn btn-danger-ghost btn-sm" data-act="rm" data-id="${escapeAttr(card.id)}">移除</button>
          </div>
        </article>`;
    }
    html += `</section>`;
  }
  list.innerHTML = html;
  updateCartChrome();
}

/** @type {Record<string, { key: string, label: string, allLabel: string, options: {value:string,label:string}[] }>} */
const filters = {
  seller: { key: "seller", label: "出售人", allLabel: "全部出售人", options: [] },
  city: { key: "city", label: "城市", allLabel: "全部城市", options: [] },
  lang: { key: "lang", label: "语言", allLabel: "全部语言", options: [] },
  foil: {
    key: "foil",
    label: "闪卡",
    allLabel: "全部",
    options: [
      { value: "foil", label: "仅闪卡" },
      { value: "nf", label: "仅非闪" },
    ],
  },
  kind: {
    key: "kind",
    label: "版本",
    allLabel: "全部",
    options: [
      { value: "exact", label: "必须此版" },
      { value: "flex", label: "可替其他版" },
    ],
  },
};

function filterOrder() {
  return state.view === "want"
    ? ["seller", "city", "kind"]
    : ["seller", "city", "lang", "foil"];
}

const $ = (sel, root = document) => root.querySelector(sel);

function displayName(card) {
  if (card.name_zh && card.name_en && card.name_zh !== card.name_en) {
    return card.name_zh;
  }
  return card.name_printed || card.name_zh || card.name_en || card.id;
}

function secondaryName(card) {
  const primary = displayName(card);
  if (card.name_en && card.name_en !== primary) return card.name_en;
  if (card.name_zh && card.name_zh !== primary) return card.name_zh;
  return "";
}

function activeList() {
  return state.view === "want" ? state.wants : state.cards;
}

function personId(item) {
  if (state.view === "want") return item.buyer_id || item.buyer || "";
  return item.seller_id || item.seller || "";
}

function personName(item) {
  return state.view === "want" ? item.buyer || "" : item.seller || "";
}

function matches(card) {
  if (state.view === "want") {
    if (state.kind !== "all" && card.kind !== state.kind) return false;
    if (state.seller !== "all" && personId(card) !== state.seller && card.buyer !== state.seller) {
      return false;
    }
  } else {
    if (state.lang !== "all" && card.lang !== state.lang) return false;
    if (state.foil === "foil" && !card.foil) return false;
    if (state.foil === "nf" && card.foil) return false;
    if (state.seller !== "all" && card.seller_id !== state.seller && card.seller !== state.seller) {
      return false;
    }
  }
  if (state.city !== "all" && card.city !== state.city) return false;

  const q = state.query.trim().toLowerCase();
  if (!q) return true;

  const hay = [
    card.name_en,
    card.name_zh,
    card.name_printed,
    card.name_query,
    card.set,
    card.set_name,
    card.number,
    card.lang_label,
    card.type_line,
    card.text,
    card.note,
    card.seller,
    card.buyer,
    card.city,
    card.contact,
    card.foil ? "foil 闪" : "",
    card.kind === "exact" || card.must ? "必须 指定 此版" : "",
    card.kind === "flex" || card.must === false ? "可替 任意 其他版" : "",
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  return q.split(/\s+/).every((token) => hay.includes(token));
}

function sellerLine(card) {
  const name = personName(card);
  const parts = [name, card.city].filter(Boolean);
  return parts.join(" · ");
}

function isNarrow() {
  return window.matchMedia("(max-width: 720px)").matches;
}

function setScrollLock(locked) {
  document.body.classList.toggle("scroll-lock", locked);
}

function restorePortaledMenus() {
  document.querySelectorAll(".dd-menu.is-portal").forEach((menu) => {
    const homeId = menu.dataset.home;
    const home = homeId ? document.getElementById(homeId) : null;
    menu.classList.remove("is-portal");
    delete menu.dataset.home;
    if (home) home.appendChild(menu);
  });
}

/** 把菜单放到触发按钮正下方，贴合筛选条而不是从屏幕底部弹出 */
function positionPortaledMenu(dd, menu) {
  const trigger = dd.querySelector(".dd-trigger");
  if (!trigger) return;

  const rect = trigger.getBoundingClientRect();
  const gap = 6;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const maxW = Math.min(288, vw - 16);
  const minW = Math.max(rect.width, 148);

  // 先设宽度再量高度，避免超出视口
  menu.style.minWidth = `${minW}px`;
  menu.style.maxWidth = `${maxW}px`;
  menu.style.top = "0px";
  menu.style.left = "0px";

  const menuH = Math.min(menu.scrollHeight || 240, vh * 0.5);
  let top = rect.bottom + gap;
  // 下方空间不够则翻到按钮上方
  if (top + menuH > vh - 8 && rect.top > menuH + gap + 8) {
    top = Math.max(8, rect.top - gap - menuH);
  }
  let left = rect.left;
  if (left + minW > vw - 8) left = Math.max(8, vw - 8 - minW);
  if (left < 8) left = 8;

  menu.style.top = `${Math.round(top)}px`;
  menu.style.left = `${Math.round(left)}px`;
  menu.style.right = "auto";
  menu.style.bottom = "auto";
}

/** 窄屏把菜单挂到 body，避免 sticky/overflow 层叠把选项盖住 */
function portalMenuIfNeeded(dd, open) {
  const menu = dd.querySelector(".dd-menu") || findMenu(dd.dataset.filter);
  if (!menu) return;

  if (open && isNarrow()) {
    menu.dataset.home = dd.id;
    menu.classList.add("is-portal");
    document.body.appendChild(menu);
    // 等一帧让内容进 DOM 再量尺寸
    requestAnimationFrame(() => positionPortaledMenu(dd, menu));
  } else if (menu.classList.contains("is-portal")) {
    menu.classList.remove("is-portal");
    menu.style.top = "";
    menu.style.left = "";
    menu.style.right = "";
    menu.style.bottom = "";
    menu.style.minWidth = "";
    menu.style.maxWidth = "";
    delete menu.dataset.home;
    dd.appendChild(menu);
  }
}

function syncScrim() {
  const open = document.querySelector(".dd.open");
  const scrim = $("#dd-scrim");
  const narrowOpen = Boolean(open && isNarrow());

  document.body.classList.toggle("dd-open", narrowOpen);

  if (scrim) {
    scrim.hidden = !narrowOpen;
  }

  // 窄屏打开下拉时锁滚动；详情弹层另算
  if (!$("#modal")?.classList.contains("open")) {
    setScrollLock(narrowOpen);
  }
}

function cardImageSrc(card) {
  // 手机列表用 normal 足够；省流量可退 small
  if (isNarrow()) {
    return card.image?.normal || card.image?.small || "";
  }
  return card.image?.normal || card.image?.small || "";
}

function renderGrid() {
  const grid = $("#grid");
  const empty = $("#empty");
  const filtered = activeList().filter(matches);
  const isWant = state.view === "want";

  $("#visible-count").textContent = String(filtered.length);
  empty.textContent = isWant ? "没有匹配的求购" : "没有匹配的卡牌";

  if (!filtered.length) {
    grid.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  grid.innerHTML = filtered
    .map((c) => {
      const added = !isWant && inCart(c.id);
      const must = isWant && (c.must === true || c.kind === "exact");
      const flex = isWant && (c.must === false || c.kind === "flex");
      const metaLeft = `${(c.set || "").toUpperCase()} #${c.number || ""}`;
      const metaRight = c.lang_label || c.lang || "";
      return `
    <div class="card" data-id="${escapeAttr(c.id)}">
      <div class="card-media">
        <button type="button" class="card-hit" data-id="${escapeAttr(c.id)}" aria-label="${escapeAttr(displayName(c))} 图片">
          <div class="card-img-wrap">
            <img
              src="${escapeAttr(cardImageSrc(c))}"
              alt="${escapeAttr(displayName(c))}"
              loading="lazy"
              decoding="async"
            />
          </div>
        </button>
        ${
          isWant
            ? ""
            : `<button
          type="button"
          class="card-add${added ? " is-in" : ""}"
          data-id="${escapeAttr(c.id)}"
          aria-label="${added ? "已在清单" : "加入意向清单"}"
        >${added ? "已加" : "加入"}</button>`
        }
      </div>
      <button type="button" class="card-hit card-hit-info" data-id="${escapeAttr(c.id)}" aria-label="${escapeAttr(displayName(c))}">
        <div class="card-body">
          <div class="card-title-row">
            <p class="card-name">${escapeHtml(displayName(c))}</p>
            <div class="card-flags">
              ${must ? '<span class="flag flag-exact">必须</span>' : ""}
              ${flex ? '<span class="flag flag-any">可替</span>' : ""}
              ${c.foil ? '<span class="flag flag-foil">闪</span>' : ""}
              ${c.quantity > 1 ? `<span class="flag flag-qty">×${c.quantity}</span>` : ""}
            </div>
          </div>
          ${secondaryName(c) ? `<p class="card-name-en">${escapeHtml(secondaryName(c))}</p>` : ""}
          <div class="card-meta">
            <span>${escapeHtml(metaLeft)}</span>
            <span>${escapeHtml(metaRight)}</span>
          </div>
          ${sellerLine(c) ? `<p class="card-seller">${escapeHtml(sellerLine(c))}</p>` : ""}
          ${c.note ? `<p class="card-note">${escapeHtml(c.note)}</p>` : ""}
        </div>
      </button>
    </div>`;
    })
    .join("");
}

function openModal(card) {
  closeAllDropdowns();
  const modal = $("#modal");
  state.modalCardId = card.id;
  const isWant = state.view === "want";
  const must = isWant && (card.must === true || card.kind === "exact");
  const flex = isWant && (card.must === false || card.kind === "flex");

  $("#modal-img").src = card.image?.large || card.image?.normal || "";
  $("#modal-img").alt = displayName(card);
  $("#modal-title").textContent = displayName(card);
  $("#modal-en").textContent = secondaryName(card);
  $("#modal-en").hidden = !secondaryName(card);

  $("#modal-tags").innerHTML = [
    isWant
      ? `<span class="tag">${must ? "必须此版" : "可替其他版"}</span>`
      : `<span class="tag">${escapeHtml(card.lang_label || card.lang)}</span>`,
    card.foil ? '<span class="tag foil">闪卡 FOIL</span>' : "",
    `<span class="tag">×${card.quantity}</span>`,
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
  $("#modal-type").textContent = card.type_line || "—";
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
  if (card.scryfall_uri) {
    link.href = card.scryfall_uri;
    link.hidden = false;
  } else {
    link.hidden = true;
  }

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

  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  setScrollLock(true);
  const panel = modal.querySelector(".modal-panel");
  if (panel) panel.scrollTop = 0;
  $("#modal-close").focus({ preventScroll: true });
}

function closeModal() {
  const modal = $("#modal");
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  state.modalCardId = null;
  if (!state.cartOpen) setScrollLock(false);
  syncScrim();
}

function closeAllDropdowns(exceptId = null) {
  document.querySelectorAll(".dd.open").forEach((el) => {
    if (exceptId && el.id === exceptId) return;
    el.classList.remove("open");
    const btn = el.querySelector(".dd-trigger");
    if (btn) btn.setAttribute("aria-expanded", "false");
    portalMenuIfNeeded(el, false);
  });
  // 清理可能残留在 body 上的菜单（除当前仍打开的）
  document.querySelectorAll(".dd-menu.is-portal").forEach((menu) => {
    const homeId = menu.dataset.home;
    if (exceptId && homeId === exceptId) return;
    const home = homeId ? document.getElementById(homeId) : null;
    menu.classList.remove("is-portal");
    delete menu.dataset.home;
    if (home) home.appendChild(menu);
  });
  syncScrim();
}

function currentLabel(filterId) {
  const conf = filters[filterId];
  const value = state[conf.key];
  if (value === "all") return conf.allLabel;
  const hit = conf.options.find((o) => o.value === value);
  return hit ? hit.label : conf.allLabel;
}

function findMenu(filterId) {
  const root = document.getElementById(`dd-${filterId}`);
  // 可能已 portal 到 body
  return (
    document.querySelector(`.dd-menu.is-portal[data-home="dd-${filterId}"]`) ||
    root?.querySelector(".dd-menu") ||
    null
  );
}

function renderDropdown(filterId) {
  const conf = filters[filterId];
  const root = document.getElementById(`dd-${filterId}`);
  if (!root) return;

  const value = state[conf.key];
  const valueEl = root.querySelector(".dd-value");
  if (valueEl) valueEl.textContent = currentLabel(filterId);

  const menu = findMenu(filterId);
  if (!menu) return;

  const items = [{ value: "all", label: conf.allLabel }, ...conf.options];
  menu.innerHTML = items
    .map(
      (opt) => `
    <li role="none">
      <button
        type="button"
        class="dd-option"
        role="option"
        data-value="${escapeAttr(opt.value)}"
        aria-selected="${opt.value === value ? "true" : "false"}"
      >${escapeHtml(opt.label)}</button>
    </li>`
    )
    .join("");
}

function buildDropdownShell(filterId) {
  const conf = filters[filterId];
  return `
    <div class="dd" id="dd-${filterId}" data-filter="${filterId}">
      <button
        type="button"
        class="dd-trigger"
        aria-haspopup="listbox"
        aria-expanded="false"
        aria-label="${escapeAttr(conf.label)}"
      >
        <span class="dd-label">${escapeHtml(conf.label)}</span>
        <span class="dd-value">${escapeHtml(conf.allLabel)}</span>
        <span class="dd-caret" aria-hidden="true"></span>
      </button>
      <ul class="dd-menu" role="listbox" aria-label="${escapeAttr(conf.label)}"></ul>
    </div>`;
}

function mountFilters() {
  const host = $("#filters");
  host.innerHTML = filterOrder().map(buildDropdownShell).join("");

  host.addEventListener("click", (e) => {
    const trigger = e.target.closest(".dd-trigger");
    if (trigger) {
      e.stopPropagation();
      const dd = trigger.closest(".dd");
      const willOpen = !dd.classList.contains("open");
      closeAllDropdowns(willOpen ? dd.id : null);
      dd.classList.toggle("open", willOpen);
      trigger.setAttribute("aria-expanded", willOpen ? "true" : "false");
      portalMenuIfNeeded(dd, willOpen);
      // 打开后刷新选项 DOM（菜单可能已挂到 body），再锚定位置
      if (willOpen) {
        renderDropdown(dd.dataset.filter);
        const menu = findMenu(dd.dataset.filter);
        if (menu?.classList.contains("is-portal")) {
          requestAnimationFrame(() => positionPortaledMenu(dd, menu));
        }
      }
      syncScrim();
      return;
    }
  });

  // 选项可能在 body 上的 portal 菜单里，委托到 document
  document.addEventListener("click", (e) => {
    const option = e.target.closest(".dd-option");
    if (!option) return;
    const menu = option.closest(".dd-menu");
    if (!menu) return;
    e.stopPropagation();

    const homeId = menu.dataset.home || menu.closest(".dd")?.id;
    const dd = homeId ? document.getElementById(homeId) : menu.closest(".dd");
    if (!dd) return;

    const filterId = dd.dataset.filter;
    const conf = filters[filterId];
    state[conf.key] = option.dataset.value;

    dd.classList.remove("open");
    dd.querySelector(".dd-trigger")?.setAttribute("aria-expanded", "false");
    portalMenuIfNeeded(dd, false);
    // 若菜单还在 portal，先还原再 render
    if (menu.classList.contains("is-portal") && menu.dataset.home) {
      const home = document.getElementById(menu.dataset.home);
      menu.classList.remove("is-portal");
      delete menu.dataset.home;
      if (home) home.appendChild(menu);
    }
    renderDropdown(filterId);
    syncScrim();
    updateFilterToggle();
    renderGrid();
  });
}

function populateFilters() {
  const list = activeList();
  const isWant = state.view === "want";

  filters.seller.label = isWant ? "买家" : "出售人";
  filters.seller.allLabel = isWant ? "全部买家" : "全部出售人";

  const sellerMap = new Map();
  for (const c of list) {
    const id = personId(c);
    const name = personName(c);
    if (!id && !name) continue;
    const key = id || name;
    if (!sellerMap.has(key)) sellerMap.set(key, name || key);
  }
  filters.seller.options = [...sellerMap.entries()]
    .map(([id, name]) => ({ value: id, label: name }))
    .sort((a, b) => a.label.localeCompare(b.label, "zh"));

  filters.city.options = [...new Set(list.map((c) => c.city).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "zh"))
    .map((c) => ({ value: c, label: c }));

  if (!isWant) {
    const langs = [...new Set(list.map((c) => c.lang).filter(Boolean))].sort();
    const labelOf = (lang) => list.find((c) => c.lang === lang)?.lang_label || lang;
    filters.lang.options = langs.map((l) => ({ value: l, label: labelOf(l) }));
  }

  // rebuild filter shells for current view
  const host = $("#filters");
  if (host) {
    host.innerHTML = filterOrder().map(buildDropdownShell).join("");
  }
  filterOrder().forEach(renderDropdown);
  updateFilterToggle();
}

function activeFilterCount() {
  let n = 0;
  if (state.seller !== "all") n += 1;
  if (state.city !== "all") n += 1;
  if (state.view === "want") {
    if (state.kind !== "all") n += 1;
  } else {
    if (state.lang !== "all") n += 1;
    if (state.foil !== "all") n += 1;
  }
  return n;
}

function updateFilterToggle() {
  const btn = $("#filter-toggle");
  const dot = $("#filter-toggle-dot");
  if (!btn) return;
  const n = activeFilterCount();
  btn.classList.toggle("has-active", n > 0);
  if (dot) {
    dot.hidden = n <= 0;
    dot.title = n > 0 ? `${n} 项筛选生效` : "";
  }
  btn.setAttribute("aria-label", n > 0 ? `筛选（${n} 项生效）` : "筛选");
}

function setFiltersOpen(open) {
  state.filtersOpen = open;
  const bar = $("#toolbar");
  const btn = $("#filter-toggle");
  if (bar) bar.classList.toggle("filters-open", open);
  if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) {
    // 展开筛选时确保工具栏可见
    bar?.classList.remove("is-collapsed");
  } else {
    closeAllDropdowns();
  }
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
  state.filtersOpen = false;
  const search = $("#search");
  if (search) search.value = "";
  document.querySelectorAll(".view-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });
  setFiltersOpen(false);
  closeModal();
  closeCart();
  renderSiteMeta();
  populateFilters();
  renderGrid();
}

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(str) {
  return escapeHtml(str).replaceAll("'", "&#39;");
}

function bindEvents() {
  state.cart = loadCart();

  $("#view-tabs")?.addEventListener("click", (e) => {
    const tab = e.target.closest(".view-tab");
    if (!tab) return;
    setView(tab.dataset.view);
  });

  $("#search").addEventListener("input", (e) => {
    state.query = e.target.value;
    renderGrid();
  });
  $("#search").addEventListener("focus", () => {
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
    }
  });

  $("#grid").addEventListener("click", (e) => {
    const addBtn = e.target.closest(".card-add");
    if (addBtn) {
      e.preventDefault();
      e.stopPropagation();
      const id = addBtn.dataset.id;
      addToCart(id, 1);
      showToast(inCart(id) ? "已加入意向清单" : "已更新清单");
      return;
    }
    const hit = e.target.closest(".card-hit");
    if (!hit) return;
    const card = state.cards.find((c) => c.id === hit.dataset.id);
    if (card) openModal(card);
  });

  $("#modal-close").addEventListener("click", closeModal);
  $("#modal-backdrop").addEventListener("click", closeModal);
  $("#modal-add")?.addEventListener("click", () => {
    if (!state.modalCardId) return;
    addToCart(state.modalCardId, 1);
    showToast("已加入意向清单");
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
    if (act === "inc") setCartQty(id, cur + 1);
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
    () => {
      // 页面滚动时收起下拉
      if (document.querySelector(".dd.open")) closeAllDropdowns();

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

async function loadData() {
  // 在售
  let sell;
  if (window.__MTG_DATA__ && Array.isArray(window.__MTG_DATA__.cards)) {
    sell = window.__MTG_DATA__;
  } else {
    sell = await loadJsonFallback(
      [`data/cards.json?v=${Date.now()}`, "data/cards.json"],
      (d) => d && Array.isArray(d.cards)
    );
  }

  // 求购（可选，失败则空列表）
  let wants = { wants: [] };
  if (window.__MTG_WANTS__ && Array.isArray(window.__MTG_WANTS__.wants)) {
    wants = window.__MTG_WANTS__;
  } else {
    try {
      wants = await loadJsonFallback(
        [`data/wants.json?v=${Date.now()}`, "data/wants.json"],
        (d) => d && Array.isArray(d.wants)
      );
    } catch {
      wants = { wants: [] };
    }
  }

  return { sell, wants };
}

async function main() {
  mountFilters();
  bindEvents();
  const data = await loadData();
  state.cards = data.sell.cards || [];
  state.site = data.sell.site || data.wants.site || {};
  state.wants = data.wants.wants || [];
  // 清理清单里已不存在的卡
  for (const id of Object.keys(state.cart)) {
    if (!state.cards.some((c) => c.id === id)) delete state.cart[id];
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
  showLoadError(`加载失败：${detail}。可试 http://127.0.0.1:8080/ 或检查网络/代理。`);
});
