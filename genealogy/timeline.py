"""Хронология человека для вкладки «О человеке»: вертикальная линия с точками-событиями.

Свои события + браки + рождение детей, по дате. События без даты — в конце.
"""
from __future__ import annotations

from .models import Event, Person

UNDATED = 99999999
BIRTH_KINDS = ("BIRT", "CHR")


def _point(sort_key, date, title, place="", person=None, note=""):
    return {"sort": sort_key, "date": date, "title": title, "place": place,
            "person": person, "note": note}


def _event_point(e: Event, title: str | None = None, person=None):
    return _point(e.sort_key, e.date_display, title or e.label,
                  e.place.name if e.place else "", person, e.value)


def timeline(person: Person) -> list[dict]:
    points = [_event_point(e) for e in person.events.select_related("place")]
    families = person.families.select_related("partner1", "partner2") \
        .prefetch_related("events__place", "children__events__place")
    for fam in families:
        spouse = fam.partner2 if fam.partner1_id == person.pk else fam.partner1
        events = list(fam.events.all())
        marriages = [e for e in events if e.kind == "MARR"]
        for e in marriages:
            points.append(_event_point(e, "Брак", spouse))
        if not marriages and spouse:
            points.append(_point(UNDATED, "", "Брак", person=spouse))
        for e in events:
            if e.kind == "DIV":
                points.append(_event_point(e, "Развод", spouse))
        for child in fam.children.all():
            title = {"M": "Рождение сына", "F": "Рождение дочери"}.get(child.sex, "Рождение ребёнка")
            birth = next((e for k in BIRTH_KINDS for e in child.events.all() if e.kind == k), None)
            points.append(_event_point(birth, title, child) if birth
                          else _point(UNDATED, "", title, person=child))
    points.sort(key=lambda p: p["sort"])
    return points
