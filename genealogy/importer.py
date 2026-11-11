"""Импорт GEDCOM в древо пользователя (из консоли и, позже, со страницы сайта)."""
from __future__ import annotations

from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop

from tree_engine.model import Tree

from .models import Event, Family, FamilyTree, Person, Place, Source

# Названия «Другого» события записываются в базу на языке того, кто импортирует.
KIND_MAP = {"BAPM": "CHR", "CREM": ("EVEN", gettext_noop("Кремация")),
            "IMMI": ("EVEN", gettext_noop("Иммиграция")), "ENGA": ("EVEN", gettext_noop("Помолвка"))}


class GedcomImportError(ValueError):
    """Понятная пользователю причина, почему импорт невозможен."""


def _kind(tag: str) -> tuple[str, str]:
    mapped = KIND_MAP.get(tag, tag)
    if isinstance(mapped, tuple):
        return mapped[0], _(mapped[1])
    return (mapped, "") if mapped in Event.Kind.values else ("EVEN", tag)


def clear_tree(family_tree: FamilyTree) -> None:
    """Удалить из древа всех людей, семьи, места и материалы; нумерация — снова с P0001."""
    for model in (Source, Family, Person, Place):
        model.objects.filter(tree=family_tree).delete()
    family_tree.root_person = None
    family_tree.next_number = 1
    family_tree.save(update_fields=["root_person", "next_number"])


@transaction.atomic
def import_tree(family_tree: FamilyTree, tree: Tree, root_gid: str | None = None,
                replace: bool = False) -> dict:
    """Записать разобранный GEDCOM (`tree`) в древо пользователя.

    В непустое древо — только с replace=True (тогда всё прежнее удаляется).
    root_gid — кто опорный человек (например, «@I1@»); если не задан — первый в файле.
    Возвращает {"people": …, "families": …, "places": …, "root": Person | None}.
    """
    if Person.objects.filter(tree=family_tree).exists():
        if not replace:
            raise GedcomImportError(_("В древе уже есть люди."))
        clear_tree(family_tree)
    if root_gid and root_gid not in tree.people:
        raise GedcomImportError(_("Человек %(gid)s не найден в файле.") % {"gid": root_gid})

    places: dict[str, Place] = {}

    def place(name: str):
        if not name:
            return None
        if name not in places:
            places[name], _ = Place.objects.get_or_create(tree=family_tree, name=name)
        return places[name]

    # Опорный человек получает P0001: импортируем его первым.
    root_gid = root_gid or next(iter(tree.people), None)
    order = sorted(tree.people, key=lambda gid: gid != root_gid)
    people: dict[str, Person] = {}
    for gid in order:
        p = tree.people[gid]
        people[gid] = Person.objects.create(tree=family_tree, given_name=p.given, patronymic=p.patronymic,
                                            birth_surname=p.surname, sex=p.sex)
        for e in p.events:
            kind, title = _kind(e.kind)
            Event.objects.create(person=people[gid], kind=kind, title=title,
                                 date=e.date.raw if e.date else "", place=place(e.place))
    families: dict[str, Family] = {}
    for gid, f in tree.families.items():
        partners = [people[x] for x in f.partners]
        families[gid] = Family.objects.create(
            tree=family_tree,
            partner1=partners[0] if partners else None,
            partner2=partners[1] if len(partners) > 1 else None)
        for e in f.events:
            kind, title = _kind(e.kind)
            Event.objects.create(family=families[gid], kind=kind, title=title,
                                 date=e.date.raw if e.date else "", place=place(e.place))
        for c in f.children:
            Person.objects.filter(pk=people[c].pk).update(parent_family=families[gid])

    root = people.get(root_gid) if root_gid else None
    family_tree.root_person = root
    family_tree.save(update_fields=["root_person"])
    return {"people": len(people), "families": len(families), "places": len(places), "root": root}
