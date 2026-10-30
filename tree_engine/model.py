"""Модель данных ядра (в памяти).

Центральная идея (как в GEDCOM): связь «родители → дети» идёт не от человека,
а от СЕМЬИ (союза). У семьи 0, 1 или 2 партнёра и список детей.
Повторный брак = ещё одна семья. Братья/сёстры выводятся из общей семьи.
Ни одно поле человека не обязательно.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MONTHS = {m: i for i, m in enumerate(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), start=1)}


@dataclass
class FuzzyDate:
    """Генеалогическая дата: хранит исходную строку и ключ сортировки.

    Понимает «6 JAN 2007», «JAN 2007», «1745», «ABT 1850», «BEF 1790»,
    «AFT 1900», «BET 1850 AND 1860».
    """
    raw: str

    @property
    def year(self) -> int | None:
        years = re.findall(r"\b(\d{3,4})\b", self.raw)
        return int(years[0]) if years else None

    @property
    def sort_key(self) -> tuple[int, int, int]:
        tokens = self.raw.upper().split()
        year = self.year or 9999
        month = next((MONTHS[t] for t in tokens if t in MONTHS), 0)
        day = next((int(t) for t in tokens if t.isdigit() and len(t) <= 2), 0)
        return (year, month, day)

    @property
    def qualifier(self) -> str:
        first = self.raw.split()[0].upper() if self.raw.split() else ""
        return {"ABT": "~", "EST": "~", "CAL": "~", "BEF": "<", "AFT": ">"}.get(first, "")

    def short(self) -> str:
        return f"{self.qualifier}{self.year}" if self.year else "?"


@dataclass
class Event:
    kind: str                      # BIRT, CHR, DEAT, BURI, MARR, DIV, ...
    date: FuzzyDate | None = None
    place: str = ""
    known: bool = True             # «1 DEAT» без даты = «умер, дата неизвестна»


@dataclass
class Person:
    id: str
    given: str = ""                # имя
    patronymic: str = ""           # отчество
    surname: str = ""              # фамилия при рождении (девичья)
    sex: str = "U"                 # M / F / U
    external_id: str = ""          # например, ID FamilySearch
    events: list[Event] = field(default_factory=list)
    parent_family: str | None = None          # семья, где он ребёнок
    families: list[str] = field(default_factory=list)  # семьи, где он партнёр

    def event(self, kind: str) -> Event | None:
        return next((e for e in self.events if e.kind == kind), None)

    @property
    def birth(self) -> Event | None:
        return self.event("BIRT") or self.event("CHR")

    @property
    def death(self) -> Event | None:
        return self.event("DEAT") or self.event("BURI")

    @property
    def display_given(self) -> str:
        return " ".join(p for p in (self.given, self.patronymic) if p) or "?"

    @property
    def birth_key(self) -> tuple:
        b = self.birth
        return b.date.sort_key if b and b.date else (9999, 0, 0)

    def years(self) -> str:
        b, d = self.birth, self.death
        start = b.date.short() if b and b.date else ""
        if d:
            end = d.date.short() if d.date else "†"
        else:
            end = ""
        if not start and not end:
            return ""
        return f"{start or '?'}–{end}"


@dataclass
class Family:
    id: str
    partners: list[str] = field(default_factory=list)   # 0..2 id людей
    children: list[str] = field(default_factory=list)   # по порядку рождения
    events: list[Event] = field(default_factory=list)


@dataclass
class Tree:
    people: dict[str, Person] = field(default_factory=dict)
    families: dict[str, Family] = field(default_factory=dict)

    # --- удобные запросы -------------------------------------------------
    def parents(self, pid: str) -> list[str]:
        fam = self.people[pid].parent_family
        return list(self.families[fam].partners) if fam else []

    def spouses(self, pid: str) -> list[str]:
        out = []
        for fid in self.people[pid].families:
            out += [p for p in self.families[fid].partners if p != pid]
        return out

    def children(self, pid: str) -> list[str]:
        out = []
        for fid in self.people[pid].families:
            out += self.families[fid].children
        return out

    def siblings(self, pid: str) -> list[str]:
        fam = self.people[pid].parent_family
        return [c for c in self.families[fam].children if c != pid] if fam else []

    def validate(self) -> list[str]:
        """Проверка целостности: ссылки, двойное членство, островки."""
        problems = []
        for f in self.families.values():
            if len(f.partners) > 2:
                problems.append(f"Семья {f.id}: больше двух партнёров")
            for pid in f.partners + f.children:
                if pid not in self.people:
                    problems.append(f"Семья {f.id}: ссылка на несуществующего {pid}")
        if self.people:
            start = next(iter(self.people))
            if len(self.connected_from(start)) != len(self.people):
                problems.append("В древе есть островки, не связанные с остальными")
        return problems

    def connected_from(self, pid: str, exclude: str | None = None) -> set[str]:
        """Все люди, достижимые от pid через любые связи (без exclude)."""
        seen, stack = {pid}, [pid]
        while stack:
            cur = stack.pop()
            for nxt in self.parents(cur) + self.spouses(cur) + self.children(cur) + self.siblings(cur):
                if nxt != exclude and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen


def deletion_blockers(tree: Tree, pid: str) -> list[str]:
    """Почему человека нельзя удалить (пустой список = можно).

    Правила: 1) у человека нет детей (древо от него не идёт вниз);
    2) после удаления не возникает островков — все остальные люди
       остаются связаны между собой.
    """
    reasons = []
    if tree.children(pid):
        reasons.append("у человека есть дети — от него продолжается древо")
    rest = [p for p in tree.people if p != pid]
    if rest and len(tree.connected_from(rest[0], exclude=pid)) != len(rest):
        reasons.append("после удаления часть древа окажется оторванной (островок)")
    return reasons
