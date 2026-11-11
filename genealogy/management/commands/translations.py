"""python manage.py translations — обновить переводы (замена makemessages + compilemessages).

Собирает строки из кода, дописывает новые в locale/<язык>/LC_MESSAGES/*.po
(с пустым переводом), помечает устаревшие «#~» и компилирует .mo.
"""
from django.core.management.base import BaseCommand

from genealogy.i18n import compile_all, update_po_files


class Command(BaseCommand):
    help = "Собрать строки для перевода, дописать их в locale/*.po и скомпилировать .mo"

    def handle(self, *args, **options):
        missing = update_po_files()
        compiled = compile_all(force=True)
        self.stdout.write(f"Скомпилировано каталогов: {len(compiled)}")
        if not missing:
            self.stdout.write(self.style.SUCCESS("Все строки переведены."))
            return
        for path, ids in missing.items():
            self.stdout.write(self.style.WARNING(f"{path}: без перевода {len(ids)}"))
            for msgid in ids[:10]:
                self.stdout.write(f"    {msgid!r}")
            if len(ids) > 10:
                self.stdout.write(f"    …и ещё {len(ids) - 10}")
