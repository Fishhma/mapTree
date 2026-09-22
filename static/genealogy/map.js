(() => {
  const graph = window.KINSHIP_GRAPH;
  const svg = document.getElementById("kinship-map");
  const viewport = document.getElementById("viewport");
  const peopleLayer = document.getElementById("person-layer");
  const partnershipLayer = document.getElementById("partnership-layer");
  const relationshipLayer = document.getElementById("relationship-layer");
  const connectionMenu = document.getElementById("connection-menu");
  const people = new Map(graph.people.map((person) => [person.id, person]));
  let selectedId = null;
  let transform = { x: 0, y: 0, scale: 1 };
  let dragging = false;
  let start = null;

  const el = (tag, attrs = {}) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  };
  const formatYear = (value) => value ? value.slice(0, 4) : "—";
  const label = (person) => `${person.given_name} ${person.family_name}`;

  const CARD_WIDTH = 196;
  const CARD_HEIGHT = 176;
  const CARD_TOP = (person) => person.y - CARD_HEIGHT / 2;
  const CARD_BOTTOM = (person) => person.y + CARD_HEIGHT / 2;
  const addText = (group, text, attrs) => {
    const node = el("text", attrs);
    node.textContent = text;
    group.append(node);
    return node;
  };

  graph.partnerships.forEach((partnership) => {
    const a = people.get(partnership.partner_ids[0]);
    const b = people.get(partnership.partner_ids[1]);
    partnershipLayer.append(el("path", {
      d: `M ${a.x} ${CARD_BOTTOM(a)} V ${partnership.y} H ${b.x} V ${CARD_BOTTOM(b)}`,
      class: "partnership-line",
    }));
    partnershipLayer.append(el("circle", { cx: partnership.x, cy: partnership.y, r: 6, class: "partnership-junction" }));
  });
  const partnershipChildren = new Map();
  graph.parent_child.forEach((link) => {
    const key = link.partnership_id ? `${link.partnership_id}:${link.child_id}` : `person:${link.parent_id}:${link.child_id}`;
    if (!partnershipChildren.has(key)) partnershipChildren.set(key, []);
    partnershipChildren.get(key).push(link);
  });
  partnershipChildren.forEach((links) => {
    const first = links[0];
    const child = people.get(first.child_id);
    const partnership = first.partnership_id && graph.partnerships.find((item) => item.id === first.partnership_id);
    const parent = people.get(first.parent_id);
    const sourceX = partnership ? partnership.x : parent.x;
    const sourceY = partnership ? partnership.y : CARD_BOTTOM(parent);
    const branchY = child.y - CARD_HEIGHT / 2 - 32;
    relationshipLayer.append(el("path", {
      d: `M ${sourceX} ${sourceY} V ${branchY} H ${child.x} V ${CARD_TOP(child)}`,
      class: "relationship",
      "data-parent": links.map((link) => link.parent_id).join(","),
      "data-child": first.child_id,
    }));
  });
  graph.people.forEach((person) => {
    const node = el("g", { class: "person-node", "data-id": person.id, tabindex: "0", role: "button", "aria-label": `Select ${label(person)}` });
    const left = person.x - CARD_WIDTH / 2;
    const top = CARD_TOP(person);
    const accent = person.sex === "F" ? "#d93572" : "#25a9c5";
    node.append(el("rect", { x: left, y: top, width: CARD_WIDTH, height: CARD_HEIGHT, rx: 7, class: "person-card", filter: "url(#soft-shadow)" }));
    node.append(el("rect", { x: left, y: top, width: CARD_WIDTH, height: 5, rx: 3, fill: accent, class: "card-accent" }));
    node.append(el("circle", { cx: person.x, cy: top + 48, r: 29, fill: person.sex === "F" ? "#ffd8e4" : "#b9f0fa", class: "avatar-bg" }));
    node.append(el("path", { d: `M ${person.x - 14} ${top + 58} Q ${person.x - 12} ${top + 39} ${person.x} ${top + 37} Q ${person.x + 12} ${top + 39} ${person.x + 14} ${top + 58} Z`, fill: person.sex === "F" ? "#9d0f4b" : "#006887", class: "avatar-silhouette" }));
    node.append(el("circle", { cx: person.x, cy: top + 37, r: 9, fill: person.sex === "F" ? "#9d0f4b" : "#006887" }));
    const addButton = addText(node, "+", { x: left + CARD_WIDTH - 18, y: top + 30, "text-anchor": "middle", class: "card-plus", tabindex: "0", role: "button", "aria-label": `Add a person related to ${label(person)}` });
    addButton.addEventListener("click", (event) => { event.stopPropagation(); openConnectionMenu(person.id, addButton); });
    addButton.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.stopPropagation(); openConnectionMenu(person.id, addButton); } });
    addText(node, person.given_name, { x: person.x, y: top + 104, "text-anchor": "middle", class: "card-name" });
    addText(node, person.family_name, { x: person.x, y: top + 124, "text-anchor": "middle", class: "card-name" });
    addText(node, `${formatYear(person.birth_date)}–${formatYear(person.death_date) === "—" ? "living" : formatYear(person.death_date)}`, { x: person.x, y: top + 143, "text-anchor": "middle", class: "node-meta" });
    addText(node, `G1NC-${String(person.id).padStart(3, "0")}`, { x: person.x, y: top + 159, "text-anchor": "middle", class: "node-id" });
    node.addEventListener("click", () => select(person.id));
    node.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") select(person.id); });
    peopleLayer.append(node);
  });

  function select(id) {
    selectedId = id;
    document.querySelector(".details").classList.remove("details-hidden");
    document.querySelector(".map-column").classList.remove("map-expanded");
    document.getElementById("add-person-details").hidden = true;
    const person = people.get(id);
    document.querySelectorAll(".person-node").forEach((node) => node.classList.toggle("selected", Number(node.dataset.id) === id));
    const related = new Set([id]);
    graph.parent_child.forEach((link) => { if (link.parent_id === id) related.add(link.child_id); if (link.child_id === id) related.add(link.parent_id); });
    graph.partnerships.forEach((item) => { if (item.partner_ids.includes(id)) item.partner_ids.forEach((partner) => related.add(partner)); });
    document.querySelectorAll(".person-node").forEach((node) => node.classList.toggle("dimmed", !related.has(Number(node.dataset.id))));
    document.querySelectorAll(".relationship").forEach((line) => {
      const parents = line.dataset.parent.split(",").map(Number);
      line.classList.toggle("dimmed", !parents.includes(id) && Number(line.dataset.child) !== id);
    });
    document.getElementById("empty-state").hidden = true;
    document.getElementById("person-details").hidden = false;
    document.getElementById("record-initials").textContent = `${person.given_name[0]}${person.family_name[0]}`;
    document.getElementById("record-name").textContent = label(person);
    document.getElementById("record-id").textContent = `PERSON / ${String(person.id).padStart(4, "0")}`;
    document.getElementById("edit-given-name").value = person.given_name;
    document.getElementById("edit-family-name").value = person.family_name;
    document.getElementById("edit-birth-date").value = person.birth_date || "";
    document.getElementById("edit-death-date").value = person.death_date || "";
    document.getElementById("edit-sex").value = person.sex;
    document.getElementById("edit-notes").value = person.notes || "";
    const links = [];
    graph.parent_child.forEach((link) => {
      if (link.parent_id === id) links.push(["Child", people.get(link.child_id)]);
      if (link.child_id === id) links.push([people.get(link.parent_id).sex === "F" ? "Mother" : "Father", people.get(link.parent_id)]);
    });
    graph.partnerships.forEach((item) => { if (item.partner_ids.includes(id)) links.push(["Partner", people.get(item.partner_ids.find((partner) => partner !== id))]); });
    links.sort(([kindA], [kindB]) => ({ Father: 0, Mother: 1, Partner: 2, Child: 3 }[kindA] ?? 4) - ({ Father: 0, Mother: 1, Partner: 2, Child: 3 }[kindB] ?? 4));
    document.getElementById("connection-list").innerHTML = links.map(([kind, linked]) => `<li><small>${kind}</small>${label(linked)}</li>`).join("");
  }
  function openConnectionMenu(anchorId, button) {
    const frame = document.querySelector(".map-frame").getBoundingClientRect();
    const buttonRect = button.getBoundingClientRect();
    connectionMenu.style.left = `${buttonRect.left - frame.left - 12}px`;
    connectionMenu.style.top = `${buttonRect.bottom - frame.top + 8}px`;
    connectionMenu.hidden = false;
    connectionMenu.dataset.anchorId = anchorId;
  }
  function openAddPerson(anchorId, relation) {
    connectionMenu.hidden = true;
    selectedId = anchorId;
    document.getElementById("person-details").hidden = true;
    document.getElementById("empty-state").hidden = true;
    document.getElementById("add-person-details").hidden = false;
    document.getElementById("add-person-form").dataset.anchorId = anchorId;
    document.getElementById("add-relation").value = relation;
    document.getElementById("add-relation-label").textContent = `Relationship: ${relation}`;
    document.getElementById("add-person-title").textContent = `Add a person to ${label(people.get(anchorId))}`;
    document.getElementById("add-given-name").focus();
  }
  connectionMenu.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openAddPerson(Number(connectionMenu.dataset.anchorId), button.dataset.relation);
    });
  });
  document.getElementById("add-person-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("add-status");
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    data.anchor_id = Number(event.currentTarget.dataset.anchorId);
    delete data.csrfmiddlewaretoken;
    status.textContent = "Saving…";
    try {
      const response = await fetch("/api/people/add/", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]").value },
        body: JSON.stringify(data),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Unable to add person.");
      status.textContent = "Saved. Refreshing map…";
      window.location.reload();
    } catch (error) {
      status.textContent = error.message;
    }
  });
  document.getElementById("person-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("save-status");
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    delete data.csrfmiddlewaretoken;
    status.textContent = "Saving…";
    try {
      const response = await fetch(`/api/people/${selectedId}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": data.csrfmiddlewaretoken || document.querySelector("[name=csrfmiddlewaretoken]").value },
        body: JSON.stringify(data),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Unable to save record.");
      status.textContent = "Saved. Refreshing map…";
      window.location.reload();
    } catch (error) {
      status.textContent = error.message;
    }
  });
  function applyTransform() { viewport.setAttribute("transform", `translate(${transform.x} ${transform.y}) scale(${transform.scale})`); }
  function reset() { transform = { x: 0, y: 0, scale: 1 }; applyTransform(); }
  document.getElementById("reset-view").addEventListener("click", reset);
  document.getElementById("fit-view").addEventListener("click", reset);
  document.getElementById("person-search").addEventListener("input", (event) => {
    const term = event.target.value.toLowerCase();
    document.querySelectorAll(".person-node").forEach((node) => node.classList.toggle("dimmed", term && !label(people.get(Number(node.dataset.id))).toLowerCase().includes(term)));
  });
  svg.addEventListener("wheel", (event) => { event.preventDefault(); transform.scale = Math.max(.65, Math.min(1.8, transform.scale + (event.deltaY < 0 ? .08 : -.08))); applyTransform(); }, { passive: false });
  svg.addEventListener("pointerdown", (event) => { if (event.target.closest(".person-node")) return; dragging = true; start = { x: event.clientX - transform.x, y: event.clientY - transform.y }; svg.setPointerCapture(event.pointerId); });
  svg.addEventListener("pointermove", (event) => { if (!dragging) return; transform.x = event.clientX - start.x; transform.y = event.clientY - start.y; applyTransform(); });
  svg.addEventListener("pointerup", () => { dragging = false; });
  svg.addEventListener("click", (event) => {
    if (!event.target.closest(".person-node") && !event.target.closest(".card-plus")) {
      connectionMenu.hidden = true;
        document.querySelector(".details").classList.add("details-hidden");
        document.querySelector(".map-column").classList.add("map-expanded");
      }
  });
  document.addEventListener("click", (event) => {
      if (!event.target.closest(".details") && !event.target.closest(".person-node") && !event.target.closest("#connection-menu")) {
        connectionMenu.hidden = true;
        document.querySelector(".details").classList.add("details-hidden");
        document.querySelector(".map-column").classList.add("map-expanded");
      }
  });
})();
