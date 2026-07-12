/* global fetch, document, window */

const state = {
  cards: [],
  site: null,
  query: "",
  lang: "all",
  foil: "all",
  set: "all",
  seller: "all",
  city: "all",
};

/** @type {Record<string, { key: string, label: string, allLabel: string, options: {value:string,label:string}[] }>} */
const filters = {
  seller: { key: "seller", label: "出售人", allLabel: "全部出售人", options: [] },
  city: { key: "city", label: "城市", allLabel: "全部城市", options: [] },
  set: { key: "set", label: "系列", allLabel: "全部系列", options: [] },
  lang: { key: "lang", label: "语言", allLabel: "全部语言", options: [] },
  foil: {
    key: "foil",
    label: "表面",
    allLabel: "全部",
    options: [
      { value: "foil", label: "仅闪卡" },
      { value: "nf", label: "仅非闪" },
    ],
  },
};

const FILTER_ORDER = ["seller", "city", "set", "lang", "foil"];

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

function matches(card) {
  if (state.lang !== "all" && card.lang !== state.lang) return false;
  if (state.foil === "foil" && !card.foil) return false;
  if (state.foil === "nf" && card.foil) return false;
  if (state.set !== "all" && card.set !== state.set) return false;
  if (state.seller !== "all" && card.seller_id !== state.seller && card.seller !== state.seller) {
    return false;
  }
  if (state.city !== "all" && card.city !== state.city) return false;

  const q = state.query.trim().toLowerCase();
  if (!q) return true;

  const hay = [
    card.name_en,
    card.name_zh,
    card.name_printed,
    card.set,
    card.set_name,
    card.number,
    card.lang_label,
    card.type_line,
    card.text,
    card.seller,
    card.city,
    card.contact,
    card.foil ? "foil 闪" : "",
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  return q.split(/\s+/).every((token) => hay.includes(token));
}

function sellerLine(card) {
  const parts = [card.seller, card.city].filter(Boolean);
  return parts.join(" · ");
}

function isNarrow() {
  return window.matchMedia("(max-width: 720px)").matches;
}

function setScrollLock(locked) {
  document.body.classList.toggle("scroll-lock", locked);
}

function syncScrim() {
  const open = document.querySelector(".dd.open");
  const scrim = $("#dd-scrim");
  if (!scrim) return;
  if (open && isNarrow()) {
    scrim.hidden = false;
  } else {
    scrim.hidden = true;
  }
  // 窄屏打开下拉时锁滚动；详情弹层另算
  if (!$("#modal")?.classList.contains("open")) {
    setScrollLock(Boolean(open && isNarrow()));
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
  const filtered = state.cards.filter(matches);

  $("#visible-count").textContent = String(filtered.length);

  if (!filtered.length) {
    grid.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  grid.innerHTML = filtered
    .map(
      (c) => `
    <button type="button" class="card" data-id="${escapeAttr(c.id)}" aria-label="${escapeAttr(displayName(c))}">
      <div class="card-img-wrap">
        <img
          src="${escapeAttr(cardImageSrc(c))}"
          alt="${escapeAttr(displayName(c))}"
          loading="lazy"
          decoding="async"
        />
        <div class="badges">
          ${c.foil ? '<span class="badge foil">FOIL</span>' : ""}
          ${c.quantity > 1 ? `<span class="badge qty">×${c.quantity}</span>` : ""}
        </div>
      </div>
      <div class="card-body">
        <p class="card-name">${escapeHtml(displayName(c))}</p>
        ${secondaryName(c) ? `<p class="card-name-en">${escapeHtml(secondaryName(c))}</p>` : ""}
        <div class="card-meta">
          <span>${escapeHtml((c.set || "").toUpperCase())} #${escapeHtml(c.number)}</span>
          <span>${escapeHtml(c.lang_label || c.lang)}</span>
        </div>
        ${sellerLine(c) ? `<p class="card-seller">${escapeHtml(sellerLine(c))}</p>` : ""}
      </div>
    </button>`
    )
    .join("");
}

function openModal(card) {
  closeAllDropdowns();
  const modal = $("#modal");
  // 手机详情用 large 清晰；桌面同样
  $("#modal-img").src = card.image?.large || card.image?.normal || "";
  $("#modal-img").alt = displayName(card);
  $("#modal-title").textContent = displayName(card);
  $("#modal-en").textContent = secondaryName(card);
  $("#modal-en").hidden = !secondaryName(card);

  $("#modal-tags").innerHTML = [
    `<span class="tag">${escapeHtml(card.lang_label || card.lang)}</span>`,
    card.foil ? '<span class="tag foil">闪卡 FOIL</span>' : "",
    `<span class="tag">×${card.quantity}</span>`,
    card.city ? `<span class="tag">${escapeHtml(card.city)}</span>` : "",
  ].join("");

  $("#modal-seller").textContent = card.seller || "—";
  $("#modal-city").textContent = card.city || "—";
  $("#modal-contact").textContent = card.contact || "—";
  $("#modal-set").textContent = `${card.set_name} (${(card.set || "").toUpperCase()})`;
  $("#modal-number").textContent = card.number;
  $("#modal-type").textContent = card.type_line || "—";
  $("#modal-text").textContent = card.text || "（无牌面文字）";

  const link = $("#modal-scryfall");
  if (card.scryfall_uri) {
    link.href = card.scryfall_uri;
    link.hidden = false;
  } else {
    link.hidden = true;
  }

  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  setScrollLock(true);
  // 抽屉打开时滚到顶部，避免上次浏览位置
  const panel = modal.querySelector(".modal-panel");
  if (panel) panel.scrollTop = 0;
  $("#modal-close").focus({ preventScroll: true });
}

function closeModal() {
  const modal = $("#modal");
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  setScrollLock(false);
  syncScrim();
}

function closeAllDropdowns(exceptId = null) {
  document.querySelectorAll(".dd.open").forEach((el) => {
    if (exceptId && el.id === exceptId) return;
    el.classList.remove("open");
    const btn = el.querySelector(".dd-trigger");
    if (btn) btn.setAttribute("aria-expanded", "false");
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

function renderDropdown(filterId) {
  const conf = filters[filterId];
  const root = document.getElementById(`dd-${filterId}`);
  if (!root) return;

  const value = state[conf.key];
  const valueEl = root.querySelector(".dd-value");
  if (valueEl) valueEl.textContent = currentLabel(filterId);

  const menu = root.querySelector(".dd-menu");
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
  host.innerHTML = FILTER_ORDER.map(buildDropdownShell).join("");

  host.addEventListener("click", (e) => {
    const trigger = e.target.closest(".dd-trigger");
    if (trigger) {
      e.stopPropagation();
      const dd = trigger.closest(".dd");
      const willOpen = !dd.classList.contains("open");
      closeAllDropdowns(willOpen ? dd.id : null);
      dd.classList.toggle("open", willOpen);
      trigger.setAttribute("aria-expanded", willOpen ? "true" : "false");
      syncScrim();
      return;
    }

    const option = e.target.closest(".dd-option");
    if (option) {
      e.stopPropagation();
      const dd = option.closest(".dd");
      const filterId = dd.dataset.filter;
      const conf = filters[filterId];
      state[conf.key] = option.dataset.value;
      dd.classList.remove("open");
      dd.querySelector(".dd-trigger").setAttribute("aria-expanded", "false");
      renderDropdown(filterId);
      syncScrim();
      renderGrid();
    }
  });
}

function populateFilters() {
  const sets = [...new Set(state.cards.map((c) => c.set).filter(Boolean))].sort();
  const langs = [...new Set(state.cards.map((c) => c.lang).filter(Boolean))].sort();

  const sellerMap = new Map();
  for (const c of state.cards) {
    if (!c.seller) continue;
    const id = c.seller_id || c.seller;
    if (!sellerMap.has(id)) sellerMap.set(id, c.seller);
  }
  filters.seller.options = [...sellerMap.entries()]
    .map(([id, name]) => ({ value: id, label: name }))
    .sort((a, b) => a.label.localeCompare(b.label, "zh"));

  filters.city.options = [...new Set(state.cards.map((c) => c.city).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "zh"))
    .map((c) => ({ value: c, label: c }));

  filters.set.options = sets.map((s) => {
    const name = state.cards.find((c) => c.set === s)?.set_name || s;
    return { value: s, label: `${s.toUpperCase()} · ${name}` };
  });

  const labelOf = (lang) => state.cards.find((c) => c.lang === lang)?.lang_label || lang;
  filters.lang.options = langs.map((l) => ({ value: l, label: labelOf(l) }));

  FILTER_ORDER.forEach(renderDropdown);
}

function renderSiteMeta() {
  const site = state.site || {};
  document.title = site.title || "万智牌库存";
  $("#site-title").textContent = site.title || "万智牌库存";
  $("#site-subtitle").textContent = site.subtitle || "";

  const contact = site.contact || {};
  $("#contact-note").textContent = contact.note || "";
  const wechat = $("#contact-wechat");
  const email = $("#contact-email");

  if (contact.wechat) {
    wechat.hidden = false;
    $("#contact-wechat-value").textContent = contact.wechat;
  } else {
    wechat.hidden = true;
  }

  if (contact.email) {
    email.hidden = false;
    const a = $("#contact-email-value");
    a.textContent = contact.email;
    a.href = `mailto:${contact.email}`;
  } else {
    email.hidden = true;
  }

  $("#total-kinds").textContent = String(state.cards.length);
  $("#total-qty").textContent = String(
    state.cards.reduce((sum, c) => sum + (c.quantity || 0), 0)
  );
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
  $("#search").addEventListener("input", (e) => {
    state.query = e.target.value;
    renderGrid();
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest(".dd") || e.target.closest("#dd-scrim")) return;
    closeAllDropdowns();
  });

  const scrim = $("#dd-scrim");
  if (scrim) {
    scrim.addEventListener("click", () => closeAllDropdowns());
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeAllDropdowns();
      closeModal();
    }
  });

  $("#grid").addEventListener("click", (e) => {
    const btn = e.target.closest(".card");
    if (!btn) return;
    const card = state.cards.find((c) => c.id === btn.dataset.id);
    if (card) openModal(card);
  });

  $("#modal-close").addEventListener("click", closeModal);
  $("#modal-backdrop").addEventListener("click", closeModal);

  const toolbar = $("#toolbar");
  const observer = new IntersectionObserver(
    ([entry]) => {
      toolbar.classList.toggle("is-stuck", entry.intersectionRatio < 1);
    },
    { threshold: [1], rootMargin: "-1px 0px 0px 0px" }
  );
  observer.observe(toolbar);
}

async function main() {
  mountFilters();
  bindEvents();
  const res = await fetch(`data/cards.json?v=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) {
    $("#empty").hidden = false;
    $("#empty").textContent = "未能加载 data/cards.json，请先运行: python3 scripts/build_data.py";
    return;
  }
  const data = await res.json();
  state.cards = data.cards || [];
  state.site = data.site || {};
  renderSiteMeta();
  populateFilters();
  renderGrid();
}

main().catch((err) => {
  console.error(err);
  $("#empty").hidden = false;
  $("#empty").textContent = "加载失败，请检查控制台。";
});
