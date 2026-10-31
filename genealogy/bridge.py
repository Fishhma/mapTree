"""Мост между базой данных и ядром: БД → tree_engine.Tree → раскладка."""
from __future__ import annotations

from tree_engine import model as engine
from tree_engine.layout import CARD_H, CARD_W, compute_layout

from .models import Event, Family, Person, TreeSettings


def build_tree() -> engine.Tree:
    tree = engine.Tree()
    for p in Person.objects.all():
        tree.people[str(p.pk)] = engine.Person(
            id=str(p.pk), given=p.given_name, patronymic=p.patronymic,
            surname=p.birth_surname, sex=p.sex,
            parent_family=str(p.parent_family_id) if p.parent_family_id else None)
    for e in Event.objects.select_related("place").filter(person__isnull=False):
        tree.people[str(e.person_id)].events.append(engine.Event(
            kind=e.kind, date=engine.FuzzyDate(e.date) if e.date else None,
            place=e.place.name if e.place else ""))
    orders = {str(p.pk): p.child_order for p in Person.objects.exclude(child_order=None)}
    for f in Family.objects.all():
        fid = str(f.pk)
        partners = [str(x) for x in (f.partner1_id, f.partner2_id) if x]
        tree.families[fid] = engine.Family(id=fid, partners=partners)
        for pid in partners:
            tree.people[pid].families.append(fid)
    for pid, person in tree.people.items():
        if person.parent_family:
            tree.families[person.parent_family].children.append(pid)
    for fam in tree.families.values():
        fam.children.sort(key=lambda c: (orders.get(c) or 999, tree.people[c].birth_key))
    return tree


def root_id(tree: engine.Tree) -> str | None:
    root = TreeSettings.get().root_person_id
    if root and str(root) in tree.people:
        return str(root)
    return next(iter(tree.people), None)


def tree_payload() -> dict:
    """Всё, что нужно браузеру для отрисовки: люди, координаты, линии."""
    tree = build_tree()
    root = root_id(tree)
    if root is None:
        return {"people": {}, "boxes": [], "unions": [], "lines": [], "rows": [],
                "width": 800, "height": 400, "card": {"w": CARD_W, "h": CARD_H},
                "root": None, "warnings": []}
    layout = compute_layout(tree, root)
    codes = dict(Person.objects.values_list("pk", "code"))
    people = {}
    for pid, p in tree.people.items():
        birth = p.birth
        people[pid] = {
            "code": codes.get(int(pid), ""),
            "given": p.given, "patronymic": p.patronymic, "surname": p.surname,
            "sex": p.sex, "years": p.years(),
            "parent_family": p.parent_family, "families": p.families,
            "birth_place": birth.place if birth else "",
        }
    return {
        "people": people,
        "boxes": [{"id": b.pid, "x": round(b.x, 1), "y": round(b.y, 1), "gen": b.gen}
                  for b in layout.boxes.values()],
        "unions": [{"id": u.fid, "x": round(u.x, 1), "y": round(u.y, 1)}
                   for u in layout.unions.values()],
        "lines": [{"kind": ln.kind, "family": ln.fid,
                   "points": [[round(x, 1), round(y, 1)] for x, y in ln.points]}
                  for ln in layout.lines],
        "rows": [{"gen": g, "y": y} for g, y in sorted(layout.rows.items())],
        "width": round(layout.width), "height": round(layout.height),
        "card": {"w": CARD_W, "h": CARD_H},
        "root": root, "warnings": layout.warnings,
    }
