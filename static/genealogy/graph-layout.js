export const CARD_WIDTH = 196;
export const CARD_HEIGHT = 176;
const CARD_GAP = 28;
const GENERATION_GAP = 330;

function comparePeople(a, b) {
  return (a.birth_date || "9999").localeCompare(b.birth_date || "9999")
    || a.family_name.localeCompare(b.family_name)
    || a.given_name.localeCompare(b.given_name)
    || a.id - b.id;
}

function graphComponents(graph) {
  const ids = graph.people.map((person) => person.id);
  const parent = new Map(ids.map((id) => [id, id]));
  const find = (id) => {
    let root = id;
    while (parent.get(root) !== root) root = parent.get(root);
    while (parent.get(id) !== id) {
      const next = parent.get(id);
      parent.set(id, root);
      id = next;
    }
    return root;
  };
  const union = (a, b) => {
    const rootA = find(a);
    const rootB = find(b);
    if (rootA !== rootB) parent.set(Math.max(rootA, rootB), Math.min(rootA, rootB));
  };
  graph.partnerships.forEach(({ partner_ids: [a, b] }) => {
    if (parent.has(a) && parent.has(b)) union(a, b);
  });
  (graph.siblings || []).forEach(({ person_ids: [a, b] }) => {
    if (parent.has(a) && parent.has(b)) union(a, b);
  });
  const components = new Map();
  graph.people.forEach((person) => {
    const key = find(person.id);
    if (!components.has(key)) components.set(key, { id: key, people: [], parents: new Set(), children: new Set(), generation: 0 });
    components.get(key).people.push(person);
  });
  const personComponent = new Map();
  components.forEach((component) => component.people.forEach((person) => personComponent.set(person.id, component.id)));
  graph.parent_child.forEach(({ parent_id, child_id }) => {
    const parentId = personComponent.get(parent_id);
    const childId = personComponent.get(child_id);
    if (parentId === undefined || childId === undefined) return;
    if (parentId === childId) {
      throw new Error("A person is both an ancestor and a partner in the same union group. The graph cannot be arranged into generations.");
    }
    components.get(parentId).children.add(childId);
    components.get(childId).parents.add(parentId);
  });
  components.forEach((component) => component.people.sort(comparePeople));
  return { components, personComponent };
}

export function calculateGenerations(graph, rootId = null) {
  const { components } = graphComponents(graph);
  const indegree = new Map([...components].map(([id, component]) => [id, component.parents.size]));
  const compareComponents = (aId, bId) => comparePeople(components.get(aId).people[0], components.get(bId).people[0]);
  const queue = [...components.keys()].filter((id) => indegree.get(id) === 0).sort(compareComponents);
  let visited = 0;
  while (queue.length) {
    const parentId = queue.shift();
    const parentComponent = components.get(parentId);
    visited += 1;
    parentComponent.children.forEach((childId) => {
      const child = components.get(childId);
      child.generation = Math.max(child.generation, parentComponent.generation + 1);
      indegree.set(childId, indegree.get(childId) - 1);
      if (indegree.get(childId) === 0) {
        queue.push(childId);
        queue.sort(compareComponents);
      }
    });
  }
  if (visited !== components.size) {
    const names = [...components.values()].filter((component) => indegree.get(component.id) > 0)
      .flatMap((component) => component.people.map((person) => person.name));
    throw new Error(`An ancestry cycle prevents generation layout: ${names.join(", ")}.`);
  }
  let rootOffset = 0;
  if (rootId !== null) {
    const rootComponentId = [...components.values()].find((component) => component.people.some((person) => person.id === rootId))?.id;
    if (rootComponentId !== undefined) rootOffset = components.get(rootComponentId).generation;
  }
  const generations = new Map();
  components.forEach((component) => component.people.forEach((person) => generations.set(person.id, component.generation - rootOffset)));
  return generations;
}

export function calculateLayout(graph, { visibleIds = new Set(graph.people.map((person) => person.id)), rootId = null } = {}) {
  const generations = calculateGenerations(graph, rootId);
  const { components, personComponent } = graphComponents(graph);
  const visiblePeople = graph.people.filter((person) => visibleIds.has(person.id));
  const visibleComponents = new Map();
  visiblePeople.forEach((person) => {
    const component = components.get(personComponent.get(person.id));
    if (!visibleComponents.has(component.id)) visibleComponents.set(component.id, { ...component, people: [] });
    visibleComponents.get(component.id).people.push(person);
  });
  visibleComponents.forEach((component) => component.people.sort(comparePeople));
  if (!visiblePeople.length) return { people: new Map(), partnerships: new Map(), width: 800, height: 500, generations };

  const lanes = new Map();
  visibleComponents.forEach((component) => {
    const generation = generations.get(component.people[0].id) ?? 0;
    if (!lanes.has(generation)) lanes.set(generation, []);
    lanes.get(generation).push(component);
  });
  const positioned = new Map();
  const laneYs = [...lanes.keys()];
  const minGeneration = Math.min(...laneYs);
  const maxGeneration = Math.max(...laneYs);
  const laneWidths = [...lanes.values()].map((lane) => (
    lane.reduce((sum, component) => sum + component.people.length * CARD_WIDTH + Math.max(0, component.people.length - 1) * CARD_GAP, 0)
    + Math.max(0, lane.length - 1) * 72
  ));
  const graphWidth = Math.max(800, ...laneWidths.map((width) => width + 80));
  const orderedGenerations = [...lanes.keys()].sort((a, b) => a - b);
  orderedGenerations.forEach((generation) => {
    const lane = lanes.get(generation);
    lane.sort((a, b) => {
      const parentMean = (component) => {
        const parentXs = [...component.parents].flatMap((id) => {
          const visibleParent = visibleComponents.get(id);
          return visibleParent?.people.map((person) => positioned.get(person.id)?.x).filter(Number.isFinite) || [];
        });
        return parentXs.length ? parentXs.reduce((sum, value) => sum + value, 0) / parentXs.length : null;
      };
      const av = parentMean(a);
      const bv = parentMean(b);
      return av !== null && bv !== null ? av - bv || comparePeople(a.people[0], b.people[0])
        : av !== null ? -1 : bv !== null ? 1 : comparePeople(a.people[0], b.people[0]);
    });
    const widths = lane.map((component) => component.people.length * CARD_WIDTH + Math.max(0, component.people.length - 1) * CARD_GAP);
    const laneGap = 72;
    const totalWidth = widths.reduce((sum, value) => sum + value, 0) + Math.max(0, lane.length - 1) * laneGap;
    let cursor = (graphWidth - totalWidth) / 2;
    lane.forEach((component, index) => {
      component.people.forEach((person, personIndex) => {
        positioned.set(person.id, {
          x: cursor + CARD_WIDTH / 2 + personIndex * (CARD_WIDTH + CARD_GAP),
          y: 140 + (generation - minGeneration) * GENERATION_GAP,
          generation,
        });
      });
      cursor += widths[index] + laneGap;
    });
    lane.width = totalWidth;
  });

  const partnershipPositions = new Map();
  graph.partnerships.forEach((union) => {
    const [aId, bId] = union.partner_ids;
    const a = positioned.get(aId);
    const b = positioned.get(bId);
    if (a && b) partnershipPositions.set(union.id, {
      x: (a.x + b.x) / 2,
      y: Math.max(a.y, b.y) + CARD_HEIGHT / 2 + 44,
    });
  });
  return {
    people: positioned,
    partnerships: partnershipPositions,
    width: graphWidth,
    height: Math.max(500, 140 + (maxGeneration - minGeneration) * GENERATION_GAP + CARD_HEIGHT + 100),
    generations,
  };
}
