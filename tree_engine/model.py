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
MONTH_CODES = {i: m for m, i in MONTHS.items()}

# Слова дат на языках интерфейса. Ядро не знает про Django: язык передаётся параметром
# («ru», «en», «cs»); незнакомый язык — как русский.
#   day   — «10 <месяц в род. падеже> 1962»: «10 августа 1962», «10 August 1962», «10. srpna 1962»
#   month — «<месяц> 1962»: «август 1962», «August 1962», «srpen 1962»
DATE_WORDS = {
    "ru": {"day": "{d} {m} {y}",
           "of": "января февраля марта апреля мая июня июля августа сентября октября ноября декабря",
           "month": "январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь",
           "ABT": "около", "BEF": "до", "AFT": "после", "BET": "между {a} и {b}"},
    "en": {"day": "{d} {m} {y}",
           "of": "January February March April May June July August September October November December",
           "month": "January February March April May June July August September October November December",
           "ABT": "about", "BEF": "before", "AFT": "after", "BET": "between {a} and {b}"},
    "cs": {"day": "{d}. {m} {y}",
           "of": "ledna února března dubna května června července srpna září října listopadu prosince",
           "month": "leden únor březen duben květen červen červenec srpen září říjen listopad prosinec",
           "ABT": "kolem", "BEF": "před", "AFT": "po", "BET": "mezi {a} a {b}"},
}
RU_MONTHS = DATE_WORDS["ru"]["of"].split()          # прежние имена — для совместимости
RU_MONTHS_NOM = DATE_WORDS["ru"]["month"].split()

# Месяцы словом на входе — на любом из языков, в любом падеже: «августа», «August», «srpna», «Aug».
MONTH_WORDS = {"май": 5}
for _words in DATE_WORDS.values():
    for _key in ("of", "month"):
        for _i, _w in enumerate(_words[_key].split(), start=1):
            MONTH_WORDS[_w.lower()] = _i
for _code, _i in MONTHS.items():
    MONTH_WORDS[_code.lower()] = _i
MONTH_WORDS.update({"sept": 9})

# Слова перед датой на входе (любой язык) → код GEDCOM. Длинные — раньше коротких.
_PREFIXES = [  # (варианты ввода, код GEDCOM)
    (("около", "ок.", "ок", "~", "abt", "about", "approx.", "approx", "circa", "ca.", "ca", "c.",
      "cca", "asi", "kolem", "přibližně"), "ABT"),
    (("до", "<", "bef", "before", "před"), "BEF"),
    (("после", ">", "aft", "after", "po"), "AFT"),
]
_BETWEEN = re.compile(r"(?:между|bet|between|mezi)\s+(.+?)\s+(?:и|and|a)\s+(.+)")


def _words(lang: str) -> dict:
    return DATE_WORDS.get((lang or "ru")[:2].lower(), DATE_WORDS["ru"])


def _date_core(text: str) -> str | None:
    """«10.08.1962» → «10 AUG 1962», «08.1962» → «AUG 1962», «1962» → «1962»."""
    text = text.strip()
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{3,4})", text)
    if m and 1 <= int(m[2]) <= 12 and 1 <= int(m[1]) <= 31:
        return f"{int(m[1])} {MONTH_CODES[int(m[2])]} {int(m[3])}"
    m = re.fullmatch(r"(\d{1,2})[./-](\d{3,4})", text)
    if m and 1 <= int(m[1]) <= 12:
        return f"{MONTH_CODES[int(m[1])]} {int(m[2])}"
    if re.fullmatch(r"\d{3,4}", text):
        return text
    m = re.fullmatch(r"(\d{3,4})/(\d{1,4})", text)       # двойной год: «1850/51»
    if m and int(m[1][:-len(m[2])] + m[2]) == int(m[1]) + 1:
        return f"{m[1]}/{m[2][-2:].zfill(2)}"
    # месяц словом: «10 AUG 1962», «10 августа 1962», «10. srpna 1962», «August 1962», «srpen 1962»
    m = re.fullmatch(r"(?:(\d{1,2})\.?\s+)?([^\W\d_]+)\.?\s+(\d{3,4})", text)
    if m and m[2].lower() in MONTH_WORDS:
        day, month = m[1], MONTH_CODES[MONTH_WORDS[m[2].lower()]]
        if day is None or 1 <= int(day) <= 31:
            return " ".join(x for x in (day and str(int(day)), month, m[3]) if x)
    return None


def normalize_date(text: str) -> str:
    """Ввод пользователя → строка в стиле GEDCOM. Нераспознанное остаётся как есть.

    «10.08.1962», «1962», «около 1850», «до 1790», «после 1900»,
    «1850–1860», «1850-52», «между 1850 и 1860», двойной год «1850/51»,
    месяц словом («10 августа 1962»), а также формат GEDCOM.
    Слова понимаются на всех трёх языках сразу: «about 1850», «před 1790», «mezi 1850 a 1860».
    """
    raw = " ".join(text.split())
    if not raw:
        return ""
    low = raw.lower()
    m = _BETWEEN.fullmatch(low) or \
        re.fullmatch(r"(\d{3,4})\s*[-–—]\s*(\d{1,4})", low)
    if m:
        second = m[2]
        if second.isdigit() and len(second) < len(m[1]):        # «1850-52» → 1852
            second = m[1][:-len(second)] + second
        a, b = _date_core(m[1]), _date_core(second)
        if a and b:
            return f"BET {a} AND {b}"
    for variants, code in _PREFIXES:
        for v in variants:
            if low.startswith(v) and (not v[-1].isalpha() or low[len(v):len(v) + 1] in (" ", "")):
                core = _date_core(raw[len(v):])
                if core:
                    return f"{code} {core}"
    return _date_core(raw) or raw


def to_user_date(raw: str, lang: str = "ru") -> str:
    """Обратно к привычному вводу: «10 AUG 1962» → «10.08.1962», «ABT 1850» → «около 1850» / «about 1850»."""
    words = _words(lang)
    def core(text: str) -> str:
        parts = text.split()
        if len(parts) == 3 and parts[1] in MONTHS:
            return f"{int(parts[0]):02d}.{MONTHS[parts[1]]:02d}.{parts[2]}"
        if len(parts) == 2 and parts[0] in MONTHS:
            return f"{MONTHS[parts[0]]:02d}.{parts[1]}"
        return text
    return _with_words(raw, core, words, fallback=lambda: core(raw.upper().strip()) if _date_core(raw) else raw)


def _with_words(raw: str, core, words: dict, fallback) -> str:
    """Общая часть показа и формы: «между … и …», «около …», «до …», «после …»."""
    up = raw.upper().strip()
    m = re.fullmatch(r"BET (.+) AND (.+)", up)
    if m:
        return words["BET"].format(a=core(m[1]), b=core(m[2]))
    for code in ("ABT", "EST", "CAL", "BEF", "AFT"):
        if up.startswith(code + " "):
            return f"{words['ABT' if code in ('EST', 'CAL') else code]} {core(up[len(code) + 1:])}"
    return fallback()


@dataclass
class FuzzyDate:
    """Генеалогическая дата: хранит исходную строку и ключ сортировки.

    Понимает «6 JAN 2007», «JAN 2007», «1745», «ABT 1850», «BEF 1790»,
    «AFT 1900», «BET 1850 AND 1860», двойной год «1850/51».
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
        """Год для карточки в древе: «1850», «~1850», «<1850», «>1850», «1850-52», «1850/51»."""
        if not self.year:
            return "?"
        m = re.fullmatch(r"BET .*?(\d{3,4}) AND .*?(\d{3,4})", self.raw.upper())
        if m:
            a, b = m[1], m[2]
            if a == b:
                return a
            return f"{a}-{b[2:]}" if len(a) == len(b) == 4 and a[:2] == b[:2] else f"{a}-{b}"
        dual = re.search(r"\b(\d{3,4}/\d{2})\b", self.raw)
        return f"{self.qualifier}{dual[1] if dual else self.year}"

    def display(self, lang: str = "ru") -> str:
        """Дата словами на языке интерфейса.

        «10 AUG 1962» → «10 августа 1962» / «10 August 1962» / «10. srpna 1962»,
        «ABT 1850» → «около 1850» / «about 1850» / «kolem 1850». Нераспознанное — как есть.
        """
        words = _words(lang)

        def core(text: str) -> str:
            parts = text.split()
            if len(parts) == 3 and parts[1] in MONTHS:
                month = words["of"].split()[MONTHS[parts[1]] - 1]
                return words["day"].format(d=int(parts[0]), m=month, y=parts[2])
            if len(parts) == 2 and parts[0] in MONTHS:
                return f"{words['month'].split()[MONTHS[parts[0]] - 1]} {parts[1]}"
            return text
        return _with_words(self.raw, core, words,
                           fallback=lambda: core(self.raw.upper()) if _date_core(self.raw) else self.raw)

    def display_ru(self) -> str:
        return self.display("ru")

    @property
    def sort_int(self) -> int:
        y, m, d = self.sort_key
        return y * 10000 + m * 100 + d


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
    events: list[Event] = field(default_factory=list)
    parent_family: str | None = None          # семья, где он ребёнок
    families: list[str] = field(default_factory=list)  # семьи, где он партнёр
    living: bool = False           # жив(а): тогда без даты смерти пишем «2007–», а не «2007–?»

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
        d = self.death
        return lifespan(self.birth.date if self.birth else None,
                        d is not None, d.date if d else None, self.living)


def lifespan(birth: FuzzyDate | None, has_death: bool, death: FuzzyDate | None,
             living: bool) -> str:
    """Годы жизни для карточки: «1849–?», «1804/05–1878», «>1800–1878», «1804–<1880», «2007–».

    Смерть неизвестна: у живого пусто («2007–»), у остальных «?».
    Если неизвестно вообще ничего — пустая строка.
    """
    start = birth.short() if birth else ""
    if has_death:
        end = death.short() if death else "?"
    else:
        end = "" if living else "?"
    if not start and end in ("", "?") and not has_death:
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

    Правила: 1) человек на краю древа — выше (родителей) или ниже (детей)
       никого нет; из середины линии удалять нельзя;
    2) после удаления не возникает островков — все остальные люди
       остаются связаны между собой.
    """
    reasons = []
    if tree.parents(pid) and tree.children(pid):
        reasons.append("у человека есть и родители, и дети — он в середине линии древа")
    rest = [p for p in tree.people if p != pid]
    if rest and len(tree.connected_from(rest[0], exclude=pid)) != len(rest):
        reasons.append("после удаления часть древа окажется оторванной (островок)")
    return reasons
