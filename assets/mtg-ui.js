/* mtg-ui.js -- 主站 + admin 共享的展示/筛选/分页层（从 app.js 抽出）。
 * 主站 app.js 在本文件之后加载，定义 cart/意向清单、详情弹窗、数据加载、view 切换；
 * 不注册 window.decorateCard -> decorateCards 钩子 no-op，cardHtml 内联购物车按钮照旧（零行为变化）。
 * admin.js override 全局 cardHtml（admin 版含 price + 编辑/删除按钮），不注册 decorateCard
 * （钩子对 admin no-op，admin 把按钮直接写进自己的 cardHtml）。
 * 经典脚本共享全局（state / filters / cardHtml / matches / renderGrid / ...），CSP script-src 'self' 无需调整。
 */
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
  type: "all", // creature | instant | …
  cmc: "all", // 0 | 1 | 2 | 3 | 4 | 5 | 6p
  /** @type {Record<string, number>} cardId -> want qty */
  cart: {},
  cartOpen: false,
  shotMode: false,
  modalCardId: null,
  filtersOpen: false,
  visibleCount: 60, // 分页：当前已渲染卡片数
  generatedAt: "", // 数据最后更新时间
  _filtered: null, // renderGrid 缓存的过滤结果，供 loadMore 复用
  anyDropdownOpen: false, // syncScrim 维护，避免 scroll handler 每次查 DOM
  cardIndex: null, // id -> card 的 Map，避免 O(n) find
};

const PAGE_SIZE = 60;

const TYPE_LABELS = {
  creature: "生物",
  instant: "瞬间",
  sorcery: "法术",
  enchantment: "结界",
  artifact: "神器",
  planeswalker: "鹏洛客",
  battle: "战役",
  land: "地",
  other: "其他",
};

const TYPE_FILTER_ORDER = [
  "creature",
  "instant",
  "sorcery",
  "enchantment",
  "artifact",
  "planeswalker",
  "battle",
  "land",
  "other",
];

const CMC_FILTER_OPTIONS = [
  { value: "0", label: "0" },
  { value: "1", label: "1" },
  { value: "2", label: "2" },
  { value: "3", label: "3" },
  { value: "4", label: "4" },
  { value: "5", label: "5" },
  { value: "6p", label: "6+" },
];

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

function trapFocus(container, e) {
  const focusable = container.querySelectorAll(
    'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])'
  );
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

let _lastFocus = null;

/** 模态/清单打开时给背景加 inert，关闭时移除（键盘/读屏用户无法触达背景） */
function setBackgroundInert(inert) {
  document
    .querySelectorAll("main, header.site-header, details.guide, .toolbar, footer, .cart-fab")
    .forEach((el) => {
      if (inert) el.setAttribute("inert", "");
      else el.removeAttribute("inert");
    });
}

function anyOverlayOpen() {
  return state.cartOpen || state.modalCardId !== null;
}

function syncInert() {
  setBackgroundInert(anyOverlayOpen());
}

/** 只允许 http(s) 的 href 赋值，防 javascript: 等 scheme 注入 */
function setHrefSafe(el, url) {
  if (el && /^https?:\/\//i.test(url || "")) {
    el.href = url;
    el.hidden = false;
  } else if (el) {
    el.hidden = true;
  }
}

/** 图片加载失败：隐藏 img 并给父容器加降级文案标记（CSS 显示「图加载失败」） */
function onImgError(img) {
  img.style.visibility = "hidden";
  img.parentElement?.classList.add("img-failed");
}

/** 给动态生成的 img 绑 error 监听（CSP 禁止 inline onerror，改用 addEventListener） */
function bindImgErrors(root) {
  root.querySelectorAll("img:not([data-eb])").forEach((img) => {
    img.dataset.eb = "1";
    img.addEventListener("error", () => onImgError(img));
    if (img.complete && img.naturalWidth === 0) onImgError(img);
  });
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
  type: {
    key: "type",
    label: "类型",
    allLabel: "全部类型",
    options: TYPE_FILTER_ORDER.map((v) => ({
      value: v,
      label: TYPE_LABELS[v] || v,
    })),
  },
  cmc: {
    key: "cmc",
    label: "费用",
    allLabel: "全部费用",
    options: CMC_FILTER_OPTIONS,
  },
};

function filterOrder() {
  return state.view === "want"
    ? ["seller", "city", "lang", "foil", "kind", "type", "cmc"]
    : ["seller", "city", "lang", "foil", "type", "cmc"];
}

function cardTypes(card) {
  if (Array.isArray(card.types) && card.types.length) return card.types;
  return [];
}

function cmcBucket(card) {
  const n = Number(card.cmc);
  if (!Number.isFinite(n) || n < 0) return "0";
  if (n >= 6) return "6p";
  return String(Math.floor(n));
}

/** 展示用：{2}{W} → 2W；无费用则空（地牌靠类型行表示） */
function formatManaCost(card) {
  const raw = (card.mana_cost || "").trim();
  if (!raw) return "";
  return raw.replaceAll("{", "").replaceAll("}", "");
}

function typeLabelShort(card) {
  const tags = cardTypes(card);
  if (!tags.length) return "";
  return tags.map((t) => TYPE_LABELS[t] || t).join("·");
}

const $ = (sel, root = document) => root.querySelector(sel);

function displayName(card) {
  if (card.name_zh && card.name_en && card.name_zh !== card.name_en) {
    return card.name_zh;
  }
  return card.name_printed || card.name_zh || card.name_en || card.id;
}

/** 卡图实际语言（非 en 卡回退 en 图时与 card.lang 不同）；相同则返回空 */
function imageLangLabel(card) {
  if (!card.image_lang || card.image_lang === card.lang) return "";
  const m = { en: "英文", zhs: "简中", ja: "日文", other: "其他" };
  return m[card.image_lang] || card.image_lang;
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
    if (state.lang !== "all" && card.lang !== state.lang) return false;
    if (state.foil === "foil" && !card.foil) return false;
    if (state.foil === "nf" && card.foil) return false;
  } else {
    if (state.lang !== "all" && card.lang !== state.lang) return false;
    if (state.foil === "foil" && !card.foil) return false;
    if (state.foil === "nf" && card.foil) return false;
    if (state.seller !== "all" && card.seller_id !== state.seller && card.seller !== state.seller) {
      return false;
    }
  }
  if (state.city !== "all" && card.city !== state.city) return false;
  if (state.type !== "all") {
    const tags = cardTypes(card);
    if (!tags.includes(state.type)) return false;
  }
  if (state.cmc !== "all" && cmcBucket(card) !== state.cmc) return false;

  const q = state.query.trim().toLowerCase();
  if (!q) return true;

  const hay = card._hay || (card._hay = buildHay(card));
  return q.split(/\s+/).every((token) => hay.includes(token));
}

function buildHay(card) {
  return [
    card.name_en,
    card.name_zh,
    card.name_printed,
    card.name_query,
    card.set,
    card.set_name,
    card.number,
    card.lang_label,
    card.type_line,
    card.type_line_en,
    typeLabelShort(card),
    card.mana_cost,
    formatManaCost(card),
    card.cmc != null ? String(card.cmc) : "",
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
  state.anyDropdownOpen = Boolean(open);
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

// 1x1 透明占位图，避免 src="" 触发对当前页 URL 的多余请求
const PLACEHOLDER_IMG =
  "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

function cardImageSrc(card) {
  // normal（488×680）优先：small（146×204）在 retina 屏放大显示发糊。
  // c7739ea 曾为省流量改回 small 优先，回退了 ce59a5c 的清晰度修复，此处恢复。
  return card.image?.normal || card.image?.small || PLACEHOLDER_IMG;
}

function cardHtml(c) {
  const isWant = state.view === "want";
  // inCart 由主站 app.js 定义（意向清单）；admin override cardHtml 不走这里。
  // 防御 typeof 以防加载顺序被重构后 inCart 缺失（主站正常情况下 app.js 已先加载并定义）。
  const added = !isWant && (typeof inCart === "function" ? inCart(c.id) : false);
  const must = isWant && (c.must === true || c.kind === "exact");
  const flex = isWant && (c.must === false || c.kind === "flex");
  const price = Number(c.price) || 0;
  const priceFlag = price > 0 ? `<span class="flag flag-price">¥${escapeHtml(price.toFixed(2))}</span>` : "";
  const metaLeft = `${(c.set || "").toUpperCase()} #${c.number || ""}`;
  const metaRight = c.lang_label || c.lang || "";
  const mana = formatManaCost(c);
  const typeShort = typeLabelShort(c);
  return `
    <div class="card" data-id="${escapeHtml(c.id)}">
      <div class="card-media">
        <button type="button" class="card-hit" data-id="${escapeHtml(c.id)}" aria-label="${escapeHtml(displayName(c))} 图片">
          <div class="card-img-wrap">
            <img
              src="${escapeHtml(cardImageSrc(c))}"
              alt="${escapeHtml(displayName(c))}"
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
          data-id="${escapeHtml(c.id)}"
          aria-label="${added ? "已在清单" : "加入意向清单"}"
        >${added ? "已加" : "加入"}</button>`
        }
      </div>
      <button type="button" class="card-hit card-hit-info" data-id="${escapeHtml(c.id)}" aria-label="${escapeHtml(displayName(c))}">
        <div class="card-body">
          <div class="card-title-row">
            <p class="card-name">${escapeHtml(displayName(c))}</p>
            <div class="card-flags">
              ${priceFlag}
              ${must ? '<span class="flag flag-exact">必须</span>' : ""}
              ${flex ? '<span class="flag flag-any">可替</span>' : ""}
              ${c.foil ? '<span class="flag flag-foil">闪</span>' : ""}
              ${c.quantity > 1 ? `<span class="flag flag-qty">×${escapeHtml(String(c.quantity))}</span>` : ""}
            </div>
          </div>
          ${secondaryName(c) ? `<p class="card-name-en">${escapeHtml(secondaryName(c))}</p>` : ""}
          <div class="card-meta">
            <span>${escapeHtml(metaLeft)}</span>
            <span>${escapeHtml(metaRight)}</span>
          </div>
          ${
            typeShort || mana
              ? `<div class="card-meta card-meta-extra">
            <span>${escapeHtml(typeShort)}</span>
            <span class="card-mana">${escapeHtml(mana)}</span>
          </div>`
              : ""
          }
          ${sellerLine(c) ? `<p class="card-seller">${escapeHtml(sellerLine(c))}</p>` : ""}
          ${c.note ? `<p class="card-note">${escapeHtml(c.note)}</p>` : ""}
        </div>
      </button>
    </div>`;
}

function renderGrid() {
  const grid = $("#grid");
  const empty = $("#empty");
  const filtered = activeList().filter(matches);
  state._filtered = filtered; // 缓存供 loadMore 复用，避免重新过滤全量
  state._filteredQuery = state.query; // 记录本次过滤用的 query，供 loadMore 检测是否过期
  const isWant = state.view === "want";

  $("#visible-count").textContent = String(filtered.length);
  empty.textContent = isWant ? "没有匹配的求购" : "没有匹配的卡牌";

  if (!filtered.length) {
    grid.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  // 分页：只渲染前 visibleCount 张，避免上千卡全量重建 DOM 卡顿
  const shown = filtered.slice(0, state.visibleCount);
  let html = shown.map(cardHtml).join("");
  if (filtered.length > shown.length) {
    html += `<button type="button" class="load-more" id="load-more">加载更多（还有 ${filtered.length - shown.length} 张）</button>`;
  }
  grid.innerHTML = html;
  bindImgErrors(grid);
  decorateCards(grid);
}

/** 增量加载下一页，不重建已渲染的卡片 DOM（只追加新页 + 刷新按钮） */
function loadMore() {
  // 搜索 debounce 期间 _filtered 可能对应旧 query（input 立即改 query 但 renderGrid
  // 延迟 150ms）；此时点加载更多应先 flush 重渲染，而非基于旧结果膨胀 visibleCount
  if (state._filteredQuery !== state.query) {
    renderGrid();
    return;
  }
  const filtered = state._filtered || activeList().filter(matches);
  const oldCount = state.visibleCount;
  state.visibleCount += PAGE_SIZE;
  const newCards = filtered.slice(oldCount, state.visibleCount);
  const grid = $("#grid");
  $("#load-more")?.remove();
  if (newCards.length) {
    grid.insertAdjacentHTML("beforeend", newCards.map(cardHtml).join(""));
  }
  if (filtered.length > state.visibleCount) {
    grid.insertAdjacentHTML(
      "beforeend",
      `<button type="button" class="load-more" id="load-more">加载更多（还有 ${filtered.length - state.visibleCount} 张）</button>`
    );
  }
  bindImgErrors(grid);
  decorateCards(grid);
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
        data-value="${escapeHtml(opt.value)}"
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
        aria-label="${escapeHtml(conf.label)}"
      >
        <span class="dd-label">${escapeHtml(conf.label)}</span>
        <span class="dd-value">${escapeHtml(conf.allLabel)}</span>
        <span class="dd-caret" aria-hidden="true"></span>
      </button>
      <ul class="dd-menu" role="listbox" aria-label="${escapeHtml(conf.label)}"></ul>
    </div>`;
}

function mountFilters() {
  const host = $("#filters");
  // shell 由 populateFilters 构建（main 里 mountFilters 后立即调 populateFilters）

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
    state.visibleCount = PAGE_SIZE;

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

  const langs = [...new Set(list.map((c) => c.lang).filter(Boolean))].sort();
  const labelOf = (lang) => list.find((c) => c.lang === lang)?.lang_label || lang;
  filters.lang.options = langs.map((l) => ({ value: l, label: labelOf(l) }));

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
  if (state.type !== "all") n += 1;
  if (state.cmc !== "all") n += 1;
  if (state.view === "want") {
    if (state.kind !== "all") n += 1;
    if (state.lang !== "all") n += 1;
    if (state.foil !== "all") n += 1;
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

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}


function decorateCards(root) {
  // 渲染后给每张卡调用 window.decorateCard(card, el)（admin 注册：注入编辑/删除按钮）。
  // 主站不注册 -> 直接返回；cardHtml 内联的购物车按钮照旧，主站行为零变化。
  if (typeof window.decorateCard !== "function") return;
  const byId = new Map(activeList().map((c) => [c.id, c]));
  root.querySelectorAll(".card[data-id]").forEach((el) => {
    const card = byId.get(el.dataset.id);
    if (card) window.decorateCard(card, el);
  });
}

