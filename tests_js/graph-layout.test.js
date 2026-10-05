import test from "node:test";
import assert from "node:assert/strict";

import { calculateGenerations, calculateLayout } from "../static/genealogy/graph-layout.js";

function person(id, birthYear = null) {
  return {
    id,
    name: `Person ${id}`,
    given_name: `Person${id}`,
    family_name: "Test",
    birth_date: birthYear ? `${birthYear}-01-01` : null,
    death_date: null,
    sex: "U",
    notes: "",
  };
}

test("generation layout supports arbitrary depth and stable coordinates", () => {
  const people = Array.from({ length: 40 }, (_, index) => person(index + 1, 1900 + index));
  const graph = {
    people,
    partnerships: [],
    siblings: [],
    parent_child: people.slice(1).map((child, index) => ({
      parent_id: people[index].id,
      child_id: child.id,
      partnership_id: null,
    })),
  };
  const first = calculateLayout(graph);
  const second = calculateLayout(graph);
  assert.equal(first.generations.get(40), 39);
  assert.equal(first.people.get(40).y - first.people.get(1).y, 39 * 330);
  assert.deepEqual([...first.people], [...second.people]);
  const rootedGenerations = calculateGenerations(graph, 20);
  assert.equal(rootedGenerations.get(20), 0);
  assert.equal(rootedGenerations.get(1), -19);
});

test("partners occupy the same generation and union child links retain their context", () => {
  const graph = {
    people: [person(1), person(2), person(3), person(4)],
    partnerships: [{ id: 10, partner_ids: [1, 2] }, { id: 11, partner_ids: [2, 3] }],
    siblings: [],
    parent_child: [
      { parent_id: 1, child_id: 4, partnership_id: 10 },
      { parent_id: 2, child_id: 4, partnership_id: 10 },
    ],
  };
  const layout = calculateLayout(graph);
  assert.equal(layout.people.get(1).generation, layout.people.get(2).generation);
  assert.equal(layout.people.get(2).generation, layout.people.get(3).generation);
  assert.equal(layout.people.get(4).generation, layout.people.get(1).generation + 1);
  assert.equal(layout.partnerships.has(10), true);
  assert.equal(layout.partnerships.has(11), true);
  assert.notEqual(layout.partnerships.get(10).x, layout.partnerships.get(11).x);
});

test("explicit siblings share a lane without creating absent parent people", () => {
  const graph = {
    people: [person(1), person(2)],
    partnerships: [],
    siblings: [{ id: 1, person_ids: [1, 2], label: "" }],
    parent_child: [],
  };
  const layout = calculateLayout(graph);
  assert.equal(layout.generations.get(1), layout.generations.get(2));
  assert.notEqual(layout.people.get(1).x, layout.people.get(2).x);
  assert.equal(layout.people.size, 2);
});

test("nodes in a generation have collision-free horizontal positions", () => {
  const graph = {
    people: Array.from({ length: 18 }, (_, index) => person(index + 1)),
    partnerships: [],
    siblings: [],
    parent_child: [],
  };
  const layout = calculateLayout(graph);
  const points = [...layout.people.values()].sort((a, b) => a.x - b.x);
  points.forEach((point, index) => {
    if (index) assert.ok(point.x - points[index - 1].x >= 196);
  });
});

test("cycle detection reports impossible generation constraints", () => {
  const graph = {
    people: [person(1), person(2)],
    partnerships: [],
    siblings: [],
    parent_child: [
      { parent_id: 1, child_id: 2 },
      { parent_id: 2, child_id: 1 },
    ],
  };
  assert.throws(() => calculateGenerations(graph), /ancestry cycle/i);
});
