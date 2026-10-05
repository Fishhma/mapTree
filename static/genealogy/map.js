import { calculateLayout } from "./graph-layout.js";
import { highlightRelationships, renderGraph } from "./graph-renderer.js";
import { connectGraphInteractions } from "./graph-interactions.js";

const svg = document.getElementById("kinship-map");
const viewport = document.getElementById("viewport");
const details = document.querySelector(".details");
const mapColumn = document.querySelector(".map-column");
const menu = document.getElementById("connection-menu");
const graphError = document.getElementById("graph-error");
let graph = JSON.parse(document.getElementById("kinship-graph-data").textContent);
let layout;
let selectedId = null;
let rootId = null;
let scope = "all";
let selectedRelativeRelation = null;
let visibleIds = new Set();

const label = (person) => `${person.given_name} ${person.family_name}`.trim();
const byId = () => new Map(graph.people.map((person) => [person.id, person]));
const peopleById = byId();
const postHeaders = () => ({
  "Content-Type": "application/json",
  "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]").value,
});

function directionalSet(direction) {
  if (selectedId === null) return new Set(graph.people.map((person) => person.id));
  const ids = new Set([selectedId]);
  const queue = [selectedId];
  const links = graph.parent_child;
  while (queue.length) {
    const current = queue.shift();
    const related = direction === "ancestors"
      ? links.filter((link) => link.child_id === current).map((link) => link.parent_id)
      : links.filter((link) => link.parent_id === current).map((link) => link.child_id);
    related.forEach((id) => {
      if (!ids.has(id)) {
        ids.add(id);
        queue.push(id);
      }
    });
  }
  (graph.siblings || []).forEach(({ person_ids }) => {
    if (person_ids.includes(selectedId)) person_ids.forEach((id) => ids.add(id));
  });
  return ids;
}

function visibilityForScope() {
  if (scope === "ancestors" || scope === "collapsed") return directionalSet("ancestors");
  if (scope === "descendants") return directionalSet("descendants");
  return new Set(graph.people.map((person) => person.id));
}

function updateSelectionPanel(person) {
  document.getElementById("empty-state").hidden = true;
  document.getElementById("add-person-details").hidden = true;
  document.getElementById("person-details").hidden = false;
  document.getElementById("record-initials").textContent = `${person.given_name[0] || ""}${person.family_name[0] || ""}`;
  document.getElementById("record-name").textContent = label(person);
  document.getElementById("edit-given-name").value = person.given_name;
  document.getElementById("edit-family-name").value = person.family_name;
  document.getElementById("edit-birth-date").value = person.birth_date || "";
  document.getElementById("edit-death-date").value = person.death_date || "";
  document.getElementById("edit-sex").value = person.sex;
  document.getElementById("edit-notes").value = person.notes || "";
  const connections = [];
  graph.parent_child.forEach((link) => {
    if (link.parent_id === person.id) connections.push(["Child", peopleById.get(link.child_id)]);
    if (link.child_id === person.id) {
      const parent = peopleById.get(link.parent_id);
      connections.push([parent.sex === "F" ? "Mother" : parent.sex === "M" ? "Father" : "Parent", parent]);
    }
  });
  graph.partnerships.forEach((union) => {
    if (union.partner_ids.includes(person.id)) {
      const other = union.partner_ids.find((id) => id !== person.id);
      connections.push(["Partner", peopleById.get(other)]);
    }
  });
  (graph.siblings || []).forEach(({ person_ids }) => {
    if (person_ids.includes(person.id)) {
      const siblingId = person_ids.find((id) => id !== person.id);
      connections.push(["Sibling", peopleById.get(siblingId)]);
    }
  });
  connections.sort(([a], [b]) => ({ Father: 0, Mother: 1, Parent: 2, Partner: 3, Sibling: 4, Child: 5 }[a] ?? 6)
    - ({ Father: 0, Mother: 1, Parent: 2, Partner: 3, Sibling: 4, Child: 5 }[b] ?? 6));
  const list = document.getElementById("connection-list");
  list.replaceChildren();
  connections.forEach(([kind, linked]) => {
    if (!linked) return;
    const item = document.createElement("li");
    const labelNode = document.createElement("small");
    labelNode.textContent = kind;
    item.append(labelNode, document.createTextNode(label(linked)));
    list.append(item);
  });
}

function render({ fit = false, focusId = null } = {}) {
  try {
    document.getElementById("person-count").textContent = String(graph.people.length).padStart(2, "0");
    visibleIds = visibilityForScope();
    layout = calculateLayout(graph, { visibleIds, rootId });
    graphError.hidden = true;
    renderGraph({
      graph,
      layout,
      svg,
      selectedId,
      onSelect: selectPerson,
      onAdd: openConnectionMenu,
    });
    if (selectedId !== null) highlightRelationships(svg, graph, selectedId);
    if (fit) controls.fit(layout, visibleIds, focusId);
  } catch (error) {
    graphError.textContent = error.message;
    graphError.hidden = false;
    console.error(error);
  }
}

function selectPerson(id) {
  selectedId = id;
  scope = "all";
  menu.hidden = true;
  details.classList.remove("details-hidden");
  mapColumn.classList.remove("map-expanded");
  updateSelectionPanel(peopleById.get(id));
  render({ fit: true, focusId: id });
}

function openConnectionMenu(anchorId, button) {
  const frame = document.querySelector(".map-frame").getBoundingClientRect();
  const buttonRect = button.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(buttonRect.left - frame.left - 12, frame.width - 210))}px`;
  menu.style.top = `${Math.min(buttonRect.bottom - frame.top + 8, frame.height - 180)}px`;
  menu.hidden = false;
  menu.dataset.anchorId = anchorId;
}

function beginAddRelative(anchorId, relation) {
  selectedRelativeRelation = relation;
  menu.hidden = true;
  details.classList.remove("details-hidden");
  mapColumn.classList.remove("map-expanded");
  document.getElementById("person-details").hidden = true;
  document.getElementById("empty-state").hidden = true;
  document.getElementById("add-person-details").hidden = false;
  document.getElementById("add-person-form").dataset.anchorId = anchorId;
  document.getElementById("add-relation").value = relation;
  document.getElementById("add-relation-label").textContent = `Relationship: ${relation}`;
  document.getElementById("add-person-title").textContent = `Add a ${relation} for ${label(peopleById.get(anchorId))}`;
  const unions = graph.partnerships.filter((union) => union.partner_ids.includes(anchorId));
  const unionField = document.getElementById("child-union-field");
  const unionSelect = document.getElementById("add-partnership");
  unionSelect.replaceChildren();
  const ownOption = new Option("This person only", "");
  unionSelect.add(ownOption);
  unions.forEach((union) => {
    const otherId = union.partner_ids.find((id) => id !== anchorId);
    unionSelect.add(new Option(`With ${label(peopleById.get(otherId))}`, union.id));
  });
  unionField.hidden = relation !== "child" || unions.length === 0;
  unionSelect.disabled = relation !== "child";
  document.getElementById("add-given-name").focus();
}

const controls = connectGraphInteractions({
  svg,
  viewport,
  onBackground: () => {
    menu.hidden = true;
    details.classList.add("details-hidden");
    mapColumn.classList.add("map-expanded");
  },
  controls: {
    zoomIn: document.getElementById("zoom-in"),
    zoomOut: document.getElementById("zoom-out"),
  },
});

menu.querySelectorAll("[data-relation]").forEach((button) => {
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    beginAddRelative(Number(menu.dataset.anchorId), button.dataset.relation);
  });
});

document.getElementById("add-person-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const status = document.getElementById("add-status");
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.anchor_id = Number(form.dataset.anchorId);
  payload.relation = selectedRelativeRelation;
  if (payload.partnership_id) payload.partnership_id = Number(payload.partnership_id);
  else delete payload.partnership_id;
  delete payload.csrfmiddlewaretoken;
  status.textContent = "Saving…";
  try {
    const response = await fetch("/api/people/add/", { method: "POST", headers: postHeaders(), body: JSON.stringify(payload) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Unable to add this relative.");
    graph = await fetch("/api/graph/").then((res) => {
      if (!res.ok) throw new Error("The new person was saved, but the graph could not be refreshed.");
      return res.json();
    });
    peopleById.clear();
    graph.people.forEach((person) => peopleById.set(person.id, person));
    selectedId = result.person.id;
    rootId = null;
    scope = "all";
    updateSelectionPanel(peopleById.get(selectedId));
    render({ fit: true, focusId: selectedId });
    status.textContent = "Person added.";
  } catch (error) {
    status.textContent = error.message;
  }
});

document.getElementById("person-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("save-status");
  const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
  delete payload.csrfmiddlewaretoken;
  status.textContent = "Saving…";
  try {
    const response = await fetch(`/api/people/${selectedId}/`, { method: "POST", headers: postHeaders(), body: JSON.stringify(payload) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Unable to save this record.");
    graph = await fetch("/api/graph/").then((res) => res.json());
    peopleById.clear();
    graph.people.forEach((person) => peopleById.set(person.id, person));
    updateSelectionPanel(peopleById.get(selectedId));
    render();
    status.textContent = "Saved.";
  } catch (error) {
    status.textContent = error.message;
  }
});

function applyScope(nextScope) {
  scope = nextScope;
  if (scope !== "all" && selectedId === null) {
    graphError.textContent = "Select a person first.";
    graphError.hidden = false;
    return;
  }
  render({ fit: true, focusId: selectedId });
}

document.getElementById("show-tree").addEventListener("click", () => {
  scope = "all";
  rootId = null;
  selectedId = null;
  menu.hidden = true;
  document.getElementById("person-details").hidden = true;
  document.getElementById("add-person-details").hidden = true;
  document.getElementById("empty-state").hidden = false;
  render({ fit: true });
});
document.getElementById("show-ancestors").addEventListener("click", () => applyScope("ancestors"));
document.getElementById("show-descendants").addEventListener("click", () => applyScope("descendants"));
document.getElementById("collapse-branches").addEventListener("click", () => applyScope("collapsed"));
document.getElementById("set-root").addEventListener("click", () => {
  if (selectedId === null) return;
  rootId = selectedId;
  scope = "all";
  render({ fit: true, focusId: selectedId });
});
document.getElementById("center-selected").addEventListener("click", () => {
  if (selectedId !== null) controls.fit(layout, visibleIds, selectedId);
});
document.getElementById("fit-view").addEventListener("click", () => controls.fit(layout, visibleIds));
document.getElementById("person-search").addEventListener("input", (event) => {
  const term = event.target.value.trim().toLocaleLowerCase();
  svg.querySelectorAll(".person-node").forEach((node) => {
    const person = peopleById.get(Number(node.dataset.id));
    node.classList.toggle("dimmed", Boolean(term) && !label(person).toLocaleLowerCase().includes(term));
  });
  if (term) {
    const match = graph.people.find((person) => label(person).toLocaleLowerCase().includes(term));
    if (match) {
      if (!visibleIds.has(match.id)) scope = "all";
      selectPerson(match.id);
    }
  }
});

document.addEventListener("click", (event) => {
  if (event.target.closest(".details") || event.target.closest(".person-node") || event.target.closest("#connection-menu")) return;
  menu.hidden = true;
  details.classList.add("details-hidden");
  mapColumn.classList.add("map-expanded");
});

render({ fit: true });
