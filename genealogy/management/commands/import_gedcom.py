"""Импорт GEDCOM в древо пользователя:

    python manage.py import_gedcom древо.ged --user имя --root @I1@ [--replace]
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from tree_engine.gedcom import load

from genealogy.importer import GedcomImportError, import_tree
from genealogy.models import FamilyTree


class Command(BaseCommand):
    help = "Импортирует GEDCOM-файл в древо пользователя"

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--user", required=True, help="Логин владельца древа")
        parser.add_argument("--root", help="ID опорного человека в файле, например @I1@")
        parser.add_argument("--replace", action="store_true",
                            help="Сначала удалить ВСЕ данные из древа этого пользователя")

    def handle(self, path, user, root=None, replace=False, **options):
        owner = get_user_model().objects.filter(username=user).first()
        if owner is None:
            raise CommandError(f"Пользователь «{user}» не найден")
        family_tree, _ = FamilyTree.objects.get_or_create(owner=owner)
        tree = load(path)
        for problem in tree.validate():
            self.stderr.write(f"Предупреждение: {problem}")
        try:
            stats = import_tree(family_tree, tree, root, replace)
        except GedcomImportError as exc:
            hint = " Добавьте --replace, чтобы заменить их." if "уже есть" in str(exc) else ""
            raise CommandError(f"{exc}{hint}") from exc
        if options.get("verbosity", 1):
            self.stdout.write(self.style.SUCCESS(
                f"Импортировано: {stats['people']} человек, {stats['families']} семей, {stats['places']} мест."))
