// Страница человека: вкладки, сохранение без перезагрузки, строки «Других сведений», материалы.
//
// Вкладки — это #about / #sources / #memories в адресе: каждое переключение — запись
// в истории браузера, поэтому «Назад» возвращает на прежнюю вкладку, а с первой — к древу.
// Сохранение идёт через fetch: сервер присылает готовый HTML вкладки «О человеке»,
// новых записей в истории не появляется.

const TABS = ["about", "sources", "memories"];

function showTab() {
  const name = TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "about";
  document.querySelectorAll("[data-pane]").forEach((pane) => { pane.hidden = pane.dataset.pane !== name; });
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active);
  });
}
addEventListener("hashchange", showTab);
showTab();

// «О человеке» открывается без #: клик по ней не должен плодить записи «/» и «#about» подряд.
document.querySelector('[data-tab="about"]').addEventListener("click", (e) => {
  if (!location.hash || location.hash === "#about") e.preventDefault();
});

// ---------- сохранение и удаление ----------
document.addEventListener("submit", async (e) => {
  const form = e.target;
  if (!form.matches("form.edit, form.confirm")) return;
  e.preventDefault();
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  let data;
  try {
    const res = await fetch(location.pathname, {
      method: "POST", body: new FormData(form), headers: { "X-Requested-With": "fetch" },
    });
    data = await res.json();
  } catch {
    data = { status: "error", message: "Сервер не отвечает. Изменения не сохранены." };
  }
  button.disabled = false;

  if (data.status === "deleted") {
    location.replace(data.redirect);          // удалённого человека в истории не оставляем
    return;
  }
  if (form.matches(".confirm") || !data.about) {
    const error = form.querySelector(".error") || form.appendChild(document.createElement("p"));
    error.className = "error";
    error.textContent = data.message;
    error.hidden = false;
    return;
  }
  document.getElementById("person-header").innerHTML = data.header;
  document.getElementById("pane-about").innerHTML = data.about;
  document.title = document.querySelector("#person-header h1").textContent.replace(/\s+/g, " ").trim()
    + " · " + document.title.split(" · ").pop();
  const notice = document.querySelector("#pane-about .notice");
  if (notice) {
    notice.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    notice.focus({ preventScroll: true });
  }
});

// ---------- «Другие сведения»: добавление строки ----------
document.addEventListener("click", (e) => {
  const button = e.target.closest("[data-add-row]");
  if (!button) return;
  const box = button.closest("[data-formset]");
  const prefix = box.dataset.formset;
  const total = box.querySelector(`input[name="${prefix}-TOTAL_FORMS"]`);
  const html = box.querySelector("template").innerHTML.replaceAll("__prefix__", total.value);
  total.value = Number(total.value) + 1;
  box.querySelector(".rows-empty")?.remove();
  box.querySelector(".rows-list").insertAdjacentHTML("beforeend", html);
  box.querySelector(".rows-list .row:last-child select, .rows-list .row:last-child input:not([type=hidden])")?.focus();
});

// ---------- «Добавить» в «Источниках» и «Воспоминаниях» ----------
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-add-material]")) {
    const dialog = e.target.closest("[data-pane]").querySelector("dialog.add-material");
    const form = dialog.querySelector("form");
    form.reset();
    form.querySelector(".preview").hidden = true;
    form.querySelector(".error").hidden = true;
    dialog.showModal();
  }
  if (e.target.closest("[data-close-dialog]")) e.target.closest("dialog").close();
});

// Превью выбранного изображения; название по умолчанию — имя файла (его можно поменять).
document.addEventListener("change", (e) => {
  if (!e.target.matches(".material-form input[type=file]")) return;
  const form = e.target.form;
  const file = e.target.files[0];
  const preview = form.querySelector(".preview");
  if (preview.src) URL.revokeObjectURL(preview.src);
  preview.hidden = !file;
  if (!file) return;
  preview.src = URL.createObjectURL(file);
  const title = form.querySelector("[name=title]");
  if (!title.value.trim()) title.value = file.name.replace(/\.[^.]+$/, "");
});

document.addEventListener("submit", async (e) => {
  const form = e.target;
  if (!form.matches(".material-form")) return;
  e.preventDefault();
  const error = form.querySelector(".error");
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  error.hidden = true;
  let data;
  try {
    const res = await fetch(form.action, {
      method: "POST", body: new FormData(form), headers: { "X-Requested-With": "fetch" },
    });
    data = await res.json();
  } catch {
    data = { status: "error", message: "Сервер не отвечает. Материал не добавлен." };
  }
  button.disabled = false;
  if (data.status !== "success") {
    error.textContent = data.message;
    error.hidden = false;
    return;
  }
  form.closest("dialog").close();
  const pane = document.getElementById(`pane-${data.tab}`);
  pane.innerHTML = data.html;
  document.querySelector(`[data-count="${data.tab}"]`).textContent = data.count;
  pane.querySelector(".notice")?.focus();
});
