// Окно первого входа: «Загрузить GEDCOM» или «Начать с нуля».
// Файл GEDCOM отправляется дважды: сначала посмотреть, кто в нём есть, затем — импорт.

const root = document.getElementById("start");
let gedcomFile = null;

const csrfToken = () =>
  document.cookie.split("; ").find((c) => c.startsWith("csrftoken="))?.split("=")[1] ?? "";

const fold = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

function show(step) {
  root.querySelectorAll("[data-step]").forEach((el) => { el.hidden = el.dataset.step !== step; });
  const first = root.querySelector(`[data-step="${step}"] input, [data-step="${step}"] button`);
  first?.focus();
}

function setError(form, text) {
  const p = form.querySelector(".start-error");
  p.textContent = text || "";
  p.hidden = !text;
}

async function send(form, body) {
  const button = form.querySelector(".start-primary");
  button.disabled = true;
  setError(form, "");
  try {
    const response = await fetch(form.action, {
      method: "POST", body, headers: { "X-CSRFToken": csrfToken() },
    });
    const data = await response.json().catch(() => ({ error: gettext("Сервер ответил ошибкой.") }));
    if (!response.ok || data.error) throw new Error(data.error || gettext("Не получилось."));
    return data;
  } catch (exc) {
    setError(form, exc.message === "Failed to fetch" ? gettext("Нет связи с сервером.") : exc.message);
    return null;
  } finally {
    button.disabled = false;
  }
}

function finish(data) {
  // «/#P0001»: если меняется только #, браузер сам страницу не перезагрузит.
  const target = new URL(data.redirect, location.href);
  if (target.pathname === location.pathname && target.search === location.search) {
    location.hash = target.hash;
    location.reload();
  } else {
    location.href = target.href;
  }
}

root.addEventListener("click", (event) => {
  const go = event.target.closest("[data-go]");
  if (go) show(go.dataset.go);
});

// ---------- «Начать с нуля» ----------
const selfForm = root.querySelector('[data-step="self"]');
selfForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = await send(selfForm, new FormData(selfForm));
  if (data) finish(data);
});

// ---------- GEDCOM: шаг 1 — прочитать файл ----------
const fileForm = root.querySelector('[data-step="gedcom"]');
const whoForm = root.querySelector('[data-step="who"]');
const list = whoForm.querySelector("[data-people]");
const search = whoForm.querySelector(".start-search");
const importButton = whoForm.querySelector(".start-primary");

fileForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileForm.elements.file.files[0];
  if (!file) {
    setError(fileForm, gettext("Выберите файл GEDCOM (.ged)."));
    return;
  }
  const body = new FormData();
  body.append("file", file);
  body.append("action", "preview");
  const data = await send(fileForm, body);
  if (!data) return;
  gedcomFile = file;
  fillPeople(data);
  show("who");
});

function fillPeople(data) {
  const n = data.people.length;
  whoForm.querySelector("[data-summary]").textContent = [
    interpolate(ngettext("В файле %(n)s человек", "В файле %(n)s человек", n), { n }, true),
    interpolate(ngettext("и %(n)s семья.", "и %(n)s семей.", data.families), { n: data.families }, true),
    gettext("Выберите себя."),
  ].join(" ");
  const notes = whoForm.querySelector("[data-notes]");
  notes.replaceChildren(...data.notes.map((text) => Object.assign(document.createElement("li"), { textContent: text })));
  if (data.notes_total > data.notes.length) {
    notes.append(Object.assign(document.createElement("li"),
      { textContent: interpolate(gettext("…и ещё %(n)s"), { n: data.notes_total - data.notes.length }, true) }));
  }
  notes.hidden = !data.notes.length;
  list.replaceChildren(...data.people.map((p) => {
    const li = document.createElement("li");
    li.dataset.search = fold(p.name);
    li.innerHTML = `<label><input type="radio" name="root"><span class="dot ${p.sex}"></span>
      <span class="name"></span><span class="years"></span></label>`;
    li.querySelector("input").value = p.gid;
    li.querySelector(".name").textContent = p.name;
    li.querySelector(".years").textContent = p.years;
    return li;
  }));
  search.value = "";
  importButton.disabled = true;
}

search.addEventListener("input", () => {
  const q = fold(search.value.trim());
  list.querySelectorAll("li").forEach((li) => { li.hidden = q !== "" && !li.dataset.search.includes(q); });
});

list.addEventListener("change", () => { importButton.disabled = !whoForm.querySelector("input[name=root]:checked"); });

// ---------- GEDCOM: шаг 2 — импорт ----------
whoForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const chosen = whoForm.querySelector("input[name=root]:checked");
  if (!chosen || !gedcomFile) {
    setError(whoForm, gettext("Выберите себя в списке."));
    return;
  }
  const body = new FormData();
  body.append("file", gedcomFile);
  body.append("action", "import");
  body.append("root", chosen.value);
  const label = importButton.textContent;
  importButton.textContent = gettext("Загружаем…");
  const data = await send(whoForm, body);
  if (data) finish(data);
  else importButton.textContent = label;
});

show("choose");
