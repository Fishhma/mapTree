"""Импорт GEDCOM в базу:  python manage.py import_gedcom древо.ged --root @I1@ --replace"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tree_engine.gedcom import load

from genealogy.models import (Citation, Event, Family, Person, PersonName, Place, Source,
                              TreeSettings)

KIND_MAP = {"BAPM": "CHR", "CREM": ("EVEN", "Кремация"), "IMMI": ("EVEN", "Иммиграция"),
            "ENGA": ("EVEN", "Помолвка")}


def _kind(tag: str) -> tuple[str, str]:
    mapped = KIND_MAP.get(tag, tag)
    if isinstance(mapped, tuple):
        return mapped
    return (mapped, "") if mapped in Event.Kind.values else ("EVEN", tag)


class Command(BaseCommand):
    help = "Импортирует GEDCOM-файл в базу данных"

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--root", help="ID опорного человека в файле, например @I1@")
        parser.add_argument("--replace", action="store_true",
                            help="Сначала удалить ВСЕ данные из базы")

    @transaction.atomic
    def handle(self, path, root=None, replace=False, **options):
        tree = load(path)
        problems = tree.validate()
        for p in problems:
            self.stderr.write(f"Предупреждение: {p}")
        if Person.objects.exists():
            if not replace:
                raise CommandError("В базе уже есть люди. Добавьте --replace, чтобы заменить их.")
            for model in (Citation, Event, PersonName, Source, Family, Person, Place):
                model.objects.all().delete()

        places: dict[str, Place] = {}

        def place(name: str):
            if not name:
                return None
            if name not in places:
                places[name], _ = Place.objects.get_or_create(name=name)
            return places[name]

        people: dict[str, Person] = {}
        for gid, p in tree.people.items():
            people[gid] = Person.objects.create(given_name=p.given, patronymic=p.patronymic,
                                                birth_surname=p.surname, sex=p.sex)
            for e in p.events:
                kind, title = _kind(e.kind)
                Event.objects.create(person=people[gid], kind=kind, title=title,
                                     date=e.date.raw if e.date else "", place=place(e.place))
        families: dict[str, Family] = {}
        for gid, f in tree.families.items():
            partners = [people[x] for x in f.partners]
            families[gid] = Family.objects.create(
                partner1=partners[0] if partners else None,
                partner2=partners[1] if len(partners) > 1 else None)
            for e in f.events:
                kind, title = _kind(e.kind)
                Event.objects.create(family=families[gid], kind=kind, title=title,
                                     date=e.date.raw if e.date else "", place=place(e.place))
            for c in f.children:
                Person.objects.filter(pk=people[c].pk).update(parent_family=families[gid])

        root_gid = root or next(iter(tree.people), None)
        if root_gid:
            if root_gid not in people:
                raise CommandError(f"Человек {root_gid} не найден в файле")
            settings = TreeSettings.get()
            settings.root_person = people[root_gid]
            settings.save()
        if options.get("verbosity", 1):
            self.stdout.write(self.style.SUCCESS(
                f"Импортировано: {len(people)} человек, {len(families)} семей, {len(places)} мест."))
