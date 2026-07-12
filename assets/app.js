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
        <img src="${escapeAttr(c.image?.normal || c.image?.small || "")}" alt="${escapeAttr(displayName(c))}" loading="lazy" />
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
        ${
          sellerLine(c)
            ? `<p class="card-seller">${escapeHtml(sellerLine(c))}</p>`
            : ""
        }
      </div>
    </button>`
    )
    .join("");
}

function openModal(card) {
  const modal = $("#modal");
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
  $("#modal-close").focus();
}

function closeModal() {
  const modal = $("#modal");
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

function fillSelect(select, options, allLabel, valueKey = null) {
  const makeValue = (item) => (valueKey ? item[valueKey] : item);
  const makeLabel = (item) => (typeof item === "string" ? item : item.label);
  select.innerHTML =
    `<option value="all">${escapeHtml(allLabel)}</option>` +
    options
      .map((item) => {
        const value = makeValue(item);
        const label = makeLabel(item);
        return `<option value="${escapeAttr(value)}">${escapeHtml(label)}</option>`;
      })
      .join("");
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
  const sellers = [...sellerMap.entries()]
    .map(([id, name]) => ({ value: id, label: name }))
    .sort((a, b) => a.label.localeCompare(b.label, "zh"));

  const cities = [...new Set(state.cards.map((c) => c.city).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "zh")
  );

  fillSelect(
    $("#filter-set"),
    sets.map((s) => {
      const name = state.cards.find((c) => c.set === s)?.set_name || s;
      return { value: s, label: `${s.toUpperCase()} · ${name}` };
    }),
    "全部系列",
    "value"
  );

  const labelOf = (lang) => state.cards.find((c) => c.lang === lang)?.lang_label || lang;
  fillSelect(
    $("#filter-lang"),
    langs.map((l) => ({ value: l, label: labelOf(l) })),
    "全部语言",
    "value"
  );

  fillSelect($("#filter-seller"), sellers, "全部出售人", "value");
  fillSelect(
    $("#filter-city"),
    cities.map((c) => ({ value: c, label: c })),
    "全部城市",
    "value"
  );
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

function bindFilter(id, key) {
  $(id).addEventListener("change", (e) => {
    state[key] = e.target.value;
    renderGrid();
  });
}

function bindEvents() {
  $("#search").addEventListener("input", (e) => {
    state.query = e.target.value;
    renderGrid();
  });

  bindFilter("#filter-lang", "lang");
  bindFilter("#filter-set", "set");
  bindFilter("#filter-foil", "foil");
  bindFilter("#filter-seller", "seller");
  bindFilter("#filter-city", "city");

  $("#grid").addEventListener("click", (e) => {
    const btn = e.target.closest(".card");
    if (!btn) return;
    const card = state.cards.find((c) => c.id === btn.dataset.id);
    if (card) openModal(card);
  });

  $("#modal-close").addEventListener("click", closeModal);
  $("#modal-backdrop").addEventListener("click", closeModal);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

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
  bindEvents();
  const res = await fetch("data/cards.json", { cache: "no-store" });
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
