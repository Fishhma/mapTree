// Страница древа: рисует готовую раскладку с сервера, перемещение/масштаб,
// поиск, выделение связей, панель с карточкой человека и «+» для добавления родственников.
// Вся геометрия считается на сервере (tree_engine), здесь только отрисовка.

const NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const svg = $("canvas");
const world = $("world");
const ruler = $("ruler");
const panel = $("panel");
const panelBody = $("panel-body");
const addMenu = $("add-menu");

let data = null;
let view = { x: 0, y: 0, k: 1 };
let selected = null;
const cards = new Map();          // id → <g>
const boxes = new Map();          // id → {x, y}

// ---------- утилиты ----------
function el(tag, attrs = {}, parent = null) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.append(node);
  return node;
}

function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== "") node.append(c);
  return node;
}

const measure = document.createElement("canvas").getContext("2d");
function fit(text, font, width) {
  measure.font = font;
  if (measure.measureText(text).width <= width) return text;
  let s = text;
  while (s.length > 1 && measure.measureText(s + "…").width > width) s = s.slice(0, -1);
  return s + "…";
}

// Поиск без учёта диакритики и алфавита: «seko» найдёт «Секо», «hanus» — «Hanuš».
const CYR = { а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z", и: "i", й: "y",
  к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "h",
  ц: "c", ч: "ch", ш: "sh", щ: "sch", ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya" };
const fold = (s) => s.toLowerCase().replace(/[а-яё]/g, (c) => CYR[c] ?? c)
  .normalize("NFD").replace(/[\u0300-\u036f]/g, "");
const fullName = (p) => [p.given, p.patronymic, p.surname].filter(Boolean).join(" ") || "?";

// ---------- отрисовка древа ----------
function draw() {
  world.replaceChildren();
  cards.clear();
  boxes.clear();
  const { w: W, h: H } = data.card;
  const linesLayer = el("g", {}, world);
  const unionsLayer = el("g", {}, world);
  const cardsLayer = el("g", {}, world);

  for (const line of data.lines) {
    el("path", {
      d: line.d,              // углы скруглены на сервере (render_svg.rounded_path)
      class: `link ${line.kind}`, "data-family": line.family,
    }, linesLayer);
  }
  for (const u of data.unions) {
    el("circle", { cx: u.x, cy: u.y, r: 3.2, class: "union", "data-family": u.id }, unionsLayer);
  }

  for (const b of data.boxes) {
    const p = data.people[b.id];
    boxes.set(b.id, b);
    const left = b.x - W / 2;
    const g = el("g", {
      class: "card" + (b.id === data.root ? " root" : ""), tabindex: "0", role: "button",
      "data-id": b.id, "aria-label": `${fullName(p)} ${p.years}`,
    }, cardsLayer);
    el("rect", { x: left, y: b.y, width: W, height: H, rx: 6, class: "card-bg" }, g);
    const accent = p.sex === "M" ? "var(--male)" : p.sex === "F" ? "var(--female)" : "var(--unknown)";
    el("rect", { x: left, y: b.y, width: W, height: 5, rx: 2, fill: accent }, g);

    const rows = [[p.given || "?", "name", "700 13px PT Sans"]];
    if (p.patronymic) rows.push([p.patronymic, "patr", "400 11px PT Sans"]);
    if (p.surname) rows.push([p.surname, "name", "700 13px PT Sans"]);
    let ty = b.y + 24;
    for (const [text, cls, font] of rows) {
      const t = el("text", { x: b.x, y: ty, "text-anchor": "middle", class: cls }, g);
      t.textContent = fit(text, font, W - 14);
      ty += cls === "patr" ? 15 : 17;
    }
    if (p.years) {
      const t = el("text", { x: b.x, y: b.y + H - 9, "text-anchor": "middle", class: "years" }, g);
      t.textContent = p.years;
    }
    // «+» в правом верхнем углу: добавить родственника. На печать (tree.svg) не попадает.
    const plus = el("g", { class: "card-plus", tabindex: "0", role: "button",
      "aria-label": `Добавить родственника: ${fullName(p)}`, "aria-haspopup": "menu" }, g);
    const cx = left + W, cy = b.y;
    el("circle", { cx, cy, r: 9 }, plus);
    el("path", { d: `M ${cx - 4} ${cy} H ${cx + 4} M ${cx} ${cy - 4} V ${cy + 4}` }, plus);
    cards.set(b.id, g);
  }
  $("stats").textContent = `${data.boxes.length} чел. · ${data.rows.length} поколений`;
}

// ---------- вид: перемещение и масштаб ----------
function apply() {
  world.setAttribute("transform", `translate(${view.x} ${view.y}) scale(${view.k})`);
  ruler.replaceChildren();
  const H = data.card.h;
  for (const r of data.rows) {
    const y = view.y + (r.y + H / 2) * view.k;
    if (y < 50 || y > innerHeight - 10) continue;
    ruler.append(h("span", { style: `top:${y}px`, title: `Поколение ${r.gen}` }, String(r.gen)));
  }
}

function zoomAt(factor, sx, sy) {
  const k = Math.min(3, Math.max(0.05, view.k * factor));
  view.x = sx - (sx - view.x) * (k / view.k);
  view.y = sy - (sy - view.y) * (k / view.k);
  view.k = k;
  apply();
}

function visibleWidth() {
  return innerWidth - (document.body.classList.contains("panel-open") ? panel.offsetWidth : 0);
}

function fitAll() {
  const pad = 60;
  const k = Math.min((visibleWidth() - pad * 2) / data.width, (innerHeight - 140) / data.height, 1.2);
  view = { k, x: (visibleWidth() - data.width * k) / 2, y: 80 + (innerHeight - 120 - data.height * k) / 2 };
  apply();
}

function centerOn(id, k = Math.max(view.k, 0.9)) {
  const b = boxes.get(id);
  if (!b) return;
  const target = { k, x: visibleWidth() / 2 - b.x * k, y: innerHeight / 2 - (b.y + data.card.h / 2) * k };
  const start = { ...view };
  const t0 = performance.now();
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const step = (now) => {
    const t = reduce ? 1 : Math.min(1, (now - t0) / 380);
    const e = 1 - (1 - t) ** 3;
    view = { x: start.x + (target.x - start.x) * e, y: start.y + (target.y - start.y) * e,
             k: start.k + (target.k - start.k) * e };
    apply();
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

let drag = null;
svg.addEventListener("pointerdown", (e) => {
  closeAddMenu();
  drag = { sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y, moved: false };
  svg.setPointerCapture(e.pointerId);
});
svg.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
  if (!drag.moved && Math.hypot(dx, dy) < 4) return;
  drag.moved = true;
  svg.classList.add("dragging");
  view.x = drag.vx + dx;
  view.y = drag.vy + dy;
  apply();
});
svg.addEventListener("pointerup", (e) => {
  const wasClick = drag && !drag.moved;
  drag = null;
  svg.classList.remove("dragging");
  if (!wasClick) return;
  const target = document.elementFromPoint(e.clientX, e.clientY);
  const plus = target?.closest(".card-plus");
  if (plus) { openAddMenu(plus.closest(".card").dataset.id, plus); return; }
  const card = target?.closest(".card");
  if (card) select(card.dataset.id);
});
svg.addEventListener("wheel", (e) => {
  e.preventDefault();
  closeAddMenu();
  zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX, e.clientY);
}, { passive: false });
svg.addEventListener("keydown", (e) => {
  const plus = e.target.closest?.(".card-plus");
  if (plus && (e.key === "Enter" || e.key === " ")) {
    e.preventDefault();
    openAddMenu(plus.closest(".card").dataset.id, plus);
    return;
  }
  const card = e.target.closest?.(".card");
  if (card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); select(card.dataset.id); }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !addMenu.hidden) { closeAddMenu({ focusBack: true }); return; }
  if (e.target.matches("input, select, textarea")) return;
  if (e.key === "+" || e.key === "=") zoomAt(1.25, visibleWidth() / 2, innerHeight / 2);
  if (e.key === "-") zoomAt(0.8, visibleWidth() / 2, innerHeight / 2);
  if (e.key === "0") fitAll();
  if (e.key === "Escape") closePanel();
});
$("zoom-in").onclick = () => zoomAt(1.25, visibleWidth() / 2, innerHeight / 2);
$("zoom-out").onclick = () => zoomAt(0.8, visibleWidth() / 2, innerHeight / 2);
$("fit").onclick = fitAll;
$("to-root").onclick = () => data.root && select(data.root);
addEventListener("resize", apply);

// ---------- выделение ----------
function highlight(id) {
  world.querySelectorAll(".hl").forEach((n) => n.classList.remove("hl"));
  world.querySelectorAll(".card.selected").forEach((n) => n.classList.remove("selected"));
  if (!id) return;
  cards.get(id)?.classList.add("selected");
  const p = data.people[id];
  const fams = [...p.families, p.parent_family].filter(Boolean);
  for (const f of fams) {
    world.querySelectorAll(`[data-family="${CSS.escape(f)}"]`).forEach((n) => n.classList.add("hl"));
  }
}

async function select(id, { center = true } = {}) {
  if (!data.people[id]) return;
  selected = id;
  highlight(id);
  history.replaceState(null, "", "#" + data.people[id].code);
  openPanel();
  if (center) centerOn(id);
  panelBody.replaceChildren(h("p", { class: "p-empty" }, "Загрузка…"));
  try {
    const res = await fetch(`/api/people/${id}/`);
    if (!res.ok) throw new Error(res.status);
    const person = await res.json();
    if (selected === id) renderPanel(person);
  } catch {
    panelBody.replaceChildren(h("p", { class: "p-empty" }, "Не удалось загрузить карточку. Обновите страницу."));
  }
}

function openPanel() {
  panel.hidden = false;
  document.body.classList.add("panel-open");
}
function closePanel() {
  panel.hidden = true;
  document.body.classList.remove("panel-open");
  selected = null;
  highlight(null);
  history.replaceState(null, "", location.pathname);
}
$("panel-close").onclick = closePanel;

// ---------- панель человека ----------
function personRow(p) {
  return h("li", {}, h("button", { type: "button", onclick: () => select(p.id) },
    h("span", { class: `dot ${p.sex}` }), h("span", {}, p.name), h("span", { class: "yrs" }, p.years)));
}

function section(title, ...content) {
  return h("section", { class: "p-section" }, h("h3", {}, title), ...content);
}

function eventList(items, emptyText) {
  if (!items.length) return h("p", { class: "p-empty" }, emptyText);
  return h("dl", { class: "facts" }, items.flatMap((e) => [
    h("dt", {}, e.label),
    h("dd", {}, [e.value, e.date].filter(Boolean).join(", ") || "—",
      e.place ? h("span", { class: "place" }, e.place) : null,
      e.description ? h("span", { class: "place" }, e.description) : null),
  ]));
}

function renderPanel(p) {
  const nodes = [
    h("div", { class: "p-head" },
      h("span", { class: `p-sex ${p.sex}` }),
      h("div", {},
        h("h2", { class: "p-name" }, p.given || "?",
          p.patronymic ? h("span", { class: "patr" }, p.patronymic) : null,
          p.surname ? h("span", {}, " ", p.surname) : null),
        h("p", { class: "p-meta" }, [p.code, p.years, p.sex_label].filter(Boolean).join(" · ")))),
    // Правка и удаление — только на отдельной странице человека (защита от случайных изменений).
    h("div", { class: "p-actions" }, h("a", { href: p.details_url }, "Изменить")),
    section("Ключевые сведения", h("dl", { class: "facts" }, p.key.flatMap((e) => [
      h("dt", {}, e.label),
      h("dd", {}, e.date || (e.place ? "" : "—"), e.place ? h("span", { class: "place" }, e.place) : null),
    ]))),
    section("Семья",
      h("h4", {}, "Родители"),
      p.parents.length ? h("ul", { class: "people" }, p.parents.map(personRow)) : h("p", { class: "p-empty" }, "Не указаны"),
      h("h4", {}, p.families.length > 1 ? "Браки и дети" : "Супруг(а) и дети"),
      p.families.length ? p.families.map((f) => h("div", { class: "union-block" },
        h("ul", { class: "people" }, f.spouse ? personRow(f.spouse) : h("li", { class: "p-empty" }, "Партнёр неизвестен")),
        f.events.length ? eventList(f.events, "") : null,
        f.children.length ? h("ul", { class: "people kids" }, f.children.map(personRow)) : null))
        : h("p", { class: "p-empty" }, "Нет"),
      p.siblings.length ? [h("h4", {}, "Братья и сёстры"), h("ul", { class: "people" }, p.siblings.map(personRow))] : null),
    section("События", eventList(p.events, "Пока нет")),
    section("Факты", eventList(p.facts, "Пока нет")),
    section("Варианты имени", p.names.length
      ? h("ul", { class: "people" }, p.names.map((n) => h("li", {}, `${n.name} — ${n.kind.toLowerCase()}`,
        n.date ? `, ${n.date}` : "", n.note ? ` (${n.note})` : "")))
      : h("p", { class: "p-empty" }, "Пока нет")),
    section(`Источники (${p.sources.length})`, p.sources.length ? p.sources.map((s) => h("div", { class: "source" },
      h("strong", {}, h("a", { href: s.admin_url }, s.title)),
      h("span", { class: "meta" }, [s.kind, s.date, s.event, s.detail].filter(Boolean).join(" · ")),
      s.repository ? h("div", { class: "meta" }, s.repository, s.reference ? `, ${s.reference}` : "") : null,
      s.files.length ? h("div", { class: "thumbs" }, s.files.map((f) => h("a", { href: f.url, target: "_blank", title: f.caption },
        f.is_image ? h("img", { src: f.url, alt: f.caption, loading: "lazy" }) : f.caption))) : null))
      : h("p", { class: "p-empty" }, "Пока нет")),
    p.notes ? section("Жизнеописание", h("p", { class: "notes" }, p.notes)) : null,
  ];
  panelBody.replaceChildren(...nodes.flat().filter(Boolean));
}

// ---------- «+»: добавление родственника ----------
const RELATIONS = {
  child: { menu: "Добавить ребёнка", title: "Новый ребёнок" },
  spouse: { menu: "Добавить супруга(у)", title: "Новый супруг(а)" },
  parent: { menu: "Добавить родителя", title: "Новый родитель" },
  sibling: { menu: "Добавить родного брата или сестру", title: "Новый брат или сестра" },
};
const UNKNOWN_PARTNER = "Второй родитель неизвестен";
let menuAnchor = null;

const parentsOf = (id) => {
  const fam = data.families[data.people[id].parent_family];
  return fam ? fam.partners : [];
};

function openAddMenu(id, anchor) {
  const items = Object.entries(RELATIONS)
    .filter(([rel]) => rel !== "parent" || parentsOf(id).length < 2)
    .map(([rel, r]) => h("button", { type: "button", role: "menuitem",
      onclick: () => { closeAddMenu(); showAddForm(id, rel); } }, r.menu));
  addMenu.replaceChildren(...items);
  addMenu.hidden = false;
  menuAnchor = anchor;
  const a = anchor.getBoundingClientRect();
  const m = addMenu.getBoundingClientRect();
  const left = Math.min(a.right + 6, innerWidth - m.width - 8);
  const top = Math.min(a.top, innerHeight - m.height - 8);
  addMenu.style.left = `${Math.max(8, left)}px`;
  addMenu.style.top = `${Math.max(8, top)}px`;
  items[0].focus();
}

function closeAddMenu({ focusBack = false } = {}) {
  if (addMenu.hidden) return;
  addMenu.hidden = true;
  if (focusBack) menuAnchor?.focus();
  menuAnchor = null;
}

addMenu.addEventListener("keydown", (e) => {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  e.preventDefault();
  const items = [...addMenu.querySelectorAll("button")];
  const i = items.indexOf(document.activeElement);
  items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
});
document.addEventListener("pointerdown", (e) => {
  if (!addMenu.contains(e.target) && !svg.contains(e.target)) closeAddMenu();
});

function field(label, input) {
  return h("label", { class: "f-field" }, h("span", {}, label), input);
}

// Варианты «второго родителя» для ребёнка: каждый союз человека + союз с неизвестным партнёром.
function unionChoices(id) {
  const choices = data.people[id].families.map((fid) => {
    const other = data.families[fid].partners.find((pid) => pid !== id);
    return { value: fid, label: other ? fullName(data.people[other]) : UNKNOWN_PARTNER };
  });
  if (!choices.some((c) => c.label === UNKNOWN_PARTNER)) choices.push({ value: "", label: UNKNOWN_PARTNER });
  return choices;
}

function showAddForm(id, relation) {
  selected = id;
  highlight(id);
  openPanel();
  const person = data.people[id];
  const places = [...new Set(Object.values(data.people).map((p) => p.birth_place).filter(Boolean))].sort();
  const error = h("p", { class: "f-error", role: "alert", hidden: true });
  const save = h("button", { type: "submit", class: "primary" }, "Сохранить");

  const unions = relation === "child"
    ? h("fieldset", { class: "f-unions" }, h("legend", {}, "Второй родитель"),
      unionChoices(id).map((c, i) => h("label", {},
        h("input", { type: "radio", name: "family", value: c.value, checked: i === 0 }), " ", c.label)))
    : null;

  const form = h("form", { class: "add-form", novalidate: true },
    unions,
    field("Имя", h("input", { name: "given_name", autocomplete: "off" })),
    field("Отчество", h("input", { name: "patronymic", autocomplete: "off" })),
    field("Фамилия при рождении", h("input", { name: "birth_surname", autocomplete: "off" })),
    field("Пол", h("select", { name: "sex" },
      h("option", { value: "U" }, "Неизвестен"), h("option", { value: "M" }, "Мужской"),
      h("option", { value: "F" }, "Женский"))),
    field("Дата рождения", h("input", { name: "birth_date", autocomplete: "off",
      placeholder: "10.08.1962 · около 1850 · 1850/51" })),
    field("Место рождения", h("input", { name: "birth_place", autocomplete: "off", list: "places" })),
    h("label", { class: "f-check" }, h("input", { type: "checkbox", name: "is_living" }), " Жив(а)"),
    h("datalist", { id: "places" }, places.map((pl) => h("option", { value: pl }))),
    h("p", { class: "f-hint" }, "Все поля необязательны."),
    error,
    h("div", { class: "p-actions" }, save,
      h("button", { type: "button", onclick: () => select(id, { center: false }) }, "Отмена")));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(form));
    body.relation = relation;
    save.disabled = true;
    error.hidden = true;
    try {
      const res = await fetch(`/api/people/${id}/add/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
        body: JSON.stringify(body),
      });
      const answer = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(answer.error || "Не удалось сохранить.");
      await loadTree();
      select(answer.id);
    } catch (err) {
      error.textContent = err instanceof TypeError ? "Сервер не отвечает." : err.message;
      error.hidden = false;
      save.disabled = false;
    }
  });

  panelBody.replaceChildren(
    h("div", { class: "p-head" }, h("span", { class: "p-sex" }),
      h("div", {}, h("h2", { class: "p-name" }, RELATIONS[relation].title),
        h("p", { class: "p-meta" }, `для: ${fullName(person)}`))),
    form);
  form.querySelector("input[name=given_name]").focus();
}

function csrfToken() {
  return document.cookie.split("; ").find((c) => c.startsWith("csrftoken="))?.split("=")[1] ?? "";
}

// ---------- поиск ----------
const searchInput = $("search");
const results = $("search-results");
let active = -1;
function runSearch() {
  const q = fold(searchInput.value.trim());
  world.querySelectorAll(".card.found").forEach((n) => n.classList.remove("found"));
  results.replaceChildren();
  active = -1;
  if (q.length < 2) { results.hidden = true; return; }
  const rank = (p) => {
    const words = fold(`${fullName(p)} ${p.code}`).split(/\s+/);
    if (words.some((w) => w === q)) return 0;
    if (words.some((w) => w.startsWith(q))) return 1;
    return words.join(" ").includes(q) ? 2 : 3;
  };
  const hits = Object.entries(data.people)
    .map(([id, p]) => [id, p, rank(p)])
    .filter(([, , r]) => r < 3)
    .sort((a, b) => a[2] - b[2])
    .slice(0, 12);
  for (const [id] of hits) cards.get(id)?.classList.add("found");
  for (const [id, p] of hits) {
    results.append(h("li", { onmousedown: (e) => { e.preventDefault(); pick(id); } },
      h("span", {}, fullName(p)), h("small", {}, [p.years, p.code].filter(Boolean).join(" · "))));
  }
  if (!hits.length) results.append(h("li", {}, h("small", {}, "Никого не найдено")));
  results.hidden = false;
}
function pick(id) {
  results.hidden = true;
  searchInput.blur();
  select(id);
}
searchInput.addEventListener("input", runSearch);
searchInput.addEventListener("blur", () => setTimeout(() => (results.hidden = true), 100));
searchInput.addEventListener("keydown", (e) => {
  const items = [...results.querySelectorAll("li")];
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items.forEach((li, i) => li.classList.toggle("active", i === active));
  } else if (e.key === "Enter") {
    const li = items[Math.max(active, 0)];
    li?.dispatchEvent(new MouseEvent("mousedown"));
  } else if (e.key === "Escape") {
    searchInput.value = "";
    runSearch();
  }
});

// ---------- запуск ----------
async function loadTree() {
  const res = await fetch("/api/tree/");
  if (!res.ok) throw new Error(res.status);
  data = await res.json();
  draw();
}

async function init() {
  try {
    await loadTree();
  } catch {
    showMessage("Не удалось загрузить древо. Проверьте, что сервер запущен.");
    return;
  }
  if (!data.boxes.length) {
    const m = showMessage("Древо пока пустое. Загрузите GEDCOM: ");
    m.append(h("code", {}, "python manage.py import_gedcom файл.ged --root @I1@"));
    return;
  }
  const fromHash = Object.entries(data.people).find(([, p]) => "#" + p.code === location.hash);
  if (fromHash) {
    openPanel();
    fitAll();
    select(fromHash[0]);
  } else {
    fitAll();
  }
  for (const w of data.warnings) console.warn("Древо:", w);
}

function showMessage(text) {
  const m = $("message");
  m.textContent = text;
  m.hidden = false;
  return m;
}

init();
