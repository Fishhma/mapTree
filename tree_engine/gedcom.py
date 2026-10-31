"""Импорт GEDCOM 5.5 / 5.5.1 (RootsMagic, FamilySearch, MyHeritage …).

Берём то, что нужно древу: имена, пол, события с датами и местами,
семьи. Остальное (служебные записи RootsMagic и т.п.) пропускаем.
"""
from __future__ import annotations

import re
from pathlib import Path

from .model import Event, Family, FuzzyDate, Person, Tree

LINE = re.compile(r"^\s*(\d+)\s+(?:(@[^@]+@)\s+)?(\S+)(?:\s(.*))?$")
PERSON_EVENTS = {"BIRT", "CHR", "BAPM", "DEAT", "BURI", "CREM", "RESI", "OCCU", "EMIG", "IMMI"}
FAMILY_EVENTS = {"MARR", "DIV", "ENGA"}
PATRONYMIC = re.compile(r"(вич|вна|ична|чна|ич)$", re.IGNORECASE)


def _split_given(given: str) -> tuple[str, str]:
    """«Юлия Евгеньевна» → («Юлия», «Евгеньевна»): отчество — второе слово
    кириллицей с типичным окончанием."""
    parts = given.split()
    if len(parts) >= 2 and re.search("[а-яё]", parts[-1], re.I) and PATRONYMIC.search(parts[-1]):
        return " ".join(parts[:-1]), parts[-1]
    return given, ""


def parse(text: str) -> Tree:
    records: list[tuple[int, str | None, str, str]] = []
    for raw in text.lstrip("\ufeff").splitlines():
        m = LINE.match(raw)
        if not m:
            continue
        level, xref, tag, value = int(m[1]), m[2], m[3], m[4] or ""
        if tag in ("CONC", "CONT") and records:
            lv, x, t, v = records[-1]
            records[-1] = (lv, x, t, v + ("\n" if tag == "CONT" else "") + value)
            continue
        records.append((level, xref, tag, value))

    tree = Tree()
    cur_person: Person | None = None
    cur_family: Family | None = None
    cur_event: Event | None = None
    in_name = False

    for level, xref, tag, value in records:
        if level == 0:
            cur_person = cur_family = cur_event = None
            if tag == "INDI":
                cur_person = tree.people.setdefault(xref, Person(id=xref))
            elif tag == "FAM":
                cur_family = tree.families.setdefault(xref, Family(id=xref))
            continue

        if level == 1:
            cur_event, in_name = None, False
            if cur_person:
                if tag == "NAME" and not (cur_person.given or cur_person.surname):
                    in_name = True
                    given = value.split("/")[0].strip()
                    surname = value.split("/")[1].strip() if value.count("/") >= 2 else ""
                    cur_person.given, cur_person.patronymic = _split_given(given)
                    cur_person.surname = surname
                elif tag == "SEX":
                    cur_person.sex = value.strip()[:1] or "U"
                elif tag == "FAMC" and cur_person.parent_family is None:
                    cur_person.parent_family = value.strip()
                elif tag == "FAMS":
                    cur_person.families.append(value.strip())
                elif tag in PERSON_EVENTS:
                    cur_event = Event(kind=tag)
                    cur_person.events.append(cur_event)
            elif cur_family:
                if tag in ("HUSB", "WIFE"):
                    cur_family.partners.append(value.strip())
                elif tag == "CHIL":
                    cur_family.children.append(value.strip())
                elif tag in FAMILY_EVENTS:
                    cur_event = Event(kind=tag)
                    cur_family.events.append(cur_event)
            continue

        if level == 2:
            if cur_event and tag == "DATE" and value.strip():
                cur_event.date = FuzzyDate(value.strip())
            elif cur_event and tag == "PLAC":
                cur_event.place = value.strip()
            elif in_name and cur_person and tag == "_MARNM":
                pass  # фамилия в браке — позже, в таблицу вариантов имени

    # Ссылки из семей главнее: дополняем то, чего нет у людей.
    for fam in tree.families.values():
        fam.partners = [p for p in fam.partners if p in tree.people]
        fam.children = [c for c in fam.children if c in tree.people]
        for p in fam.partners:
            if fam.id not in tree.people[p].families:
                tree.people[p].families.append(fam.id)
        for c in fam.children:
            if tree.people[c].parent_family is None:
                tree.people[c].parent_family = fam.id
        fam.children.sort(key=lambda c: tree.people[c].birth_key)
    return tree


def load(path: str | Path) -> Tree:
    return parse(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
