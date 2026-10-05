import { CARD_HEIGHT, CARD_WIDTH } from "./graph-layout.js";

const NS = "http://www.w3.org/2000/svg";
const measureCanvas = document.createElement("canvas");
const measureContext = measureCanvas.getContext("2d");
const CARD_NAME_FONT = '600 13px "Space Grotesk", sans-serif';
const svgElement = (tag, attrs = {}) => {
  const element = document.createElementNS(NS, tag);
  Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
};

function addText(group, value, attrs) {
  const text = svgElement("text", attrs);
  text.textContent = value;
  group.append(text);
  return text;
}

function nodeLabel(person) {
  return `${person.given_name} ${person.family_name}`.trim();
}

function fitName(value, maxWidth) {
  const characters = Array.from(value);
  measureContext.font = CARD_NAME_FONT;
  if (measureContext.measureText(value).width <= maxWidth) return value;
  while (characters.length > 1 && measureContext.measureText(`${characters.join("")}…`).width > maxWidth) {
    characters.pop();
  }
  return `${characters.join("")}…`;
}

export function renderGraph({ graph, layout, svg, selectedId, onSelect, onAdd }) {
  const svgWidth = 1020;
  const svgHeight = 620;
  svg.setAttribute("viewBox", `0 0 ${svgWidth} ${svgHeight}`);
  const viewport = svg.querySelector("#viewport");
  const background = svg.querySelector("#map-background");
  background.setAttribute("width", svgWidth);
  background.setAttribute("height", svgHeight);
  viewport.replaceChildren();
  const relationshipLayer = svgElement("g", { class: "relationship-layer" });
  const partnershipLayer = svgElement("g", { class: "partnership-layer" });
  const peopleLayer = svgElement("g", { class: "person-layer" });
  viewport.append(relationshipLayer, partnershipLayer, peopleLayer);
  const visible = layout.people;

  graph.partnerships.forEach((union) => {
    const [aId, bId] = union.partner_ids;
    const a = visible.get(aId);
    const b = visible.get(bId);
    if (!a || !b) return;
    const railY = layout.partnerships.get(union.id)?.y ?? Math.max(a.y, b.y) + CARD_HEIGHT / 2 + 44;
    partnershipLayer.append(svgElement("path", {
      d: `M ${a.x} ${a.y + CARD_HEIGHT / 2} V ${railY} H ${b.x} V ${b.y + CARD_HEIGHT / 2}`,
      class: "partnership-line",
    }));
    partnershipLayer.append(svgElement("circle", { cx: (a.x + b.x) / 2, cy: railY, r: 5, class: "partnership-junction" }));
  });
  (graph.siblings || []).forEach((siblingLink) => {
    const [aId, bId] = siblingLink.person_ids;
    const a = visible.get(aId);
    const b = visible.get(bId);
    if (!a || !b) return;
    const y = a.y + CARD_HEIGHT / 2 + 24;
    relationshipLayer.append(svgElement("path", {
      d: `M ${a.x + CARD_WIDTH / 2} ${a.y + CARD_HEIGHT / 2} V ${y} H ${b.x} V ${b.y + CARD_HEIGHT / 2}`,
      class: "sibling-relationship",
      "data-people": siblingLink.person_ids.join(","),
    }));
  });

  const childGroups = new Map();
  graph.parent_child.forEach((link) => {
    if (!visible.has(link.parent_id) || !visible.has(link.child_id)) return;
    const key = link.partnership_id ? `union:${link.partnership_id}:child:${link.child_id}` : `parent:${link.parent_id}:child:${link.child_id}`;
    if (!childGroups.has(key)) childGroups.set(key, []);
    childGroups.get(key).push(link);
  });
  childGroups.forEach((links) => {
    const first = links[0];
    const child = visible.get(first.child_id);
    const union = first.partnership_id && layout.partnerships.get(first.partnership_id);
    const soleParent = visible.get(first.parent_id);
    const sourceX = union ? union.x : soleParent.x;
    const sourceY = union ? union.y : soleParent.y + CARD_HEIGHT / 2;
    const targetY = child.y - CARD_HEIGHT / 2;
    const branchY = targetY - 26;
    relationshipLayer.append(svgElement("path", {
      d: `M ${sourceX} ${sourceY} V ${branchY} H ${child.x} V ${targetY}`,
      class: "relationship",
      "data-parents": links.map((link) => link.parent_id).join(","),
      "data-child": first.child_id,
    }));
  });

  graph.people.forEach((person) => {
    const point = visible.get(person.id);
    if (!point) return;
    const x = point.x;
    const top = point.y - CARD_HEIGHT / 2;
    const left = x - CARD_WIDTH / 2;
    const female = person.sex === "F";
    const genderColor = female ? "#d93572" : "#25a9c5";
    const group = svgElement("g", {
      class: `person-node${person.id === selectedId ? " selected" : ""}`,
      "data-id": person.id,
      tabindex: "0",
      role: "group",
      "aria-label": `Select ${nodeLabel(person)}`,
    });
    group.append(svgElement("rect", { x: left, y: top, width: CARD_WIDTH, height: CARD_HEIGHT, rx: 7, class: "person-card" }));
    group.append(svgElement("rect", { x: left, y: top, width: CARD_WIDTH, height: 5, rx: 3, fill: genderColor, class: "card-accent" }));
    group.append(svgElement("circle", { cx: x, cy: top + 48, r: 29, fill: female ? "#ffd8e4" : "#b9f0fa" }));
    group.append(svgElement("path", {
      d: `M ${x - 14} ${top + 58} Q ${x - 12} ${top + 39} ${x} ${top + 37} Q ${x + 12} ${top + 39} ${x + 14} ${top + 58} Z`,
      fill: female ? "#9d0f4b" : "#006887",
    }));
    group.append(svgElement("circle", { cx: x, cy: top + 37, r: 9, fill: female ? "#9d0f4b" : "#006887" }));
    addText(group, "+", {
      x: left + CARD_WIDTH - 18, y: top + 30, "text-anchor": "middle", class: "card-plus",
      tabindex: "0", role: "button", "aria-label": `Add a relative to ${nodeLabel(person)}`,
    }).addEventListener("click", (event) => { event.stopPropagation(); onAdd(person.id, event.currentTarget); });
    addText(group, fitName(person.given_name, CARD_WIDTH - 28), { x, y: top + 104, "text-anchor": "middle", class: "card-name" });
    addText(group, fitName(person.family_name, CARD_WIDTH - 28), { x, y: top + 124, "text-anchor": "middle", class: "card-name" });
    const years = `${person.birth_date?.slice(0, 4) || "?"}–${person.death_date?.slice(0, 4) || (person.birth_date ? "living" : "?")}`;
    addText(group, years, { x, y: top + 143, "text-anchor": "middle", class: "node-meta" });
    addText(group, `PERSON ${String(person.id).padStart(4, "0")}`, { x, y: top + 159, "text-anchor": "middle", class: "node-id" });
    group.addEventListener("click", (event) => {
      if (event.target.classList.contains("card-plus")) return;
      onSelect(person.id);
    });
    group.addEventListener("keydown", (event) => {
      if (event.target.classList.contains("card-plus")) {
        if (event.key === "Enter" || event.key === " ") onAdd(person.id, event.target);
        return;
      }
      if (event.key === "Enter" || event.key === " ") onSelect(person.id);
    });
    peopleLayer.append(group);
  });
}

export function highlightRelationships(svg, graph, selectedId) {
  const related = new Set([selectedId]);
  graph.parent_child.forEach((link) => {
    if (link.parent_id === selectedId) related.add(link.child_id);
    if (link.child_id === selectedId) related.add(link.parent_id);
  });
  graph.partnerships.forEach((union) => {
    if (union.partner_ids.includes(selectedId)) union.partner_ids.forEach((id) => related.add(id));
  });
  (graph.siblings || []).forEach(({ person_ids }) => {
    if (person_ids.includes(selectedId)) person_ids.forEach((id) => related.add(id));
  });
  svg.querySelectorAll(".person-node").forEach((node) => node.classList.toggle("dimmed", !related.has(Number(node.dataset.id))));
  svg.querySelectorAll(".relationship").forEach((path) => {
    const parents = path.dataset.parents.split(",").map(Number);
    path.classList.toggle("dimmed", !parents.includes(selectedId) && Number(path.dataset.child) !== selectedId);
  });
  svg.querySelectorAll(".sibling-relationship").forEach((path) => {
    path.classList.toggle("dimmed", !path.dataset.people.split(",").map(Number).includes(selectedId));
  });
}
