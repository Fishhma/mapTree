"""Первый вход: древо пустое — «Загрузить GEDCOM» или «Начать с нуля».

Импорт GEDCOM возможен только в пустое древо (слить файл с уже заполненным
древом — значит искать дубликаты, это отдельная задача). Если человек начал
с нуля и передумал, он удаляет древо целиком и начинает заново с импорта.

Окно на странице древа работает через fetch, ответы — JSON:
  POST /start/self/           своя карточка → P0001, опорный человек
  POST /start/gedcom/         action=preview — список людей из файла («Кто из них вы?»)
                              action=import, root=@I1@ — импорт; выбранный — P0001
Файл между шагами на сервере не хранится: браузер отправляет его ещё раз.
"""
from __future__ import annotations

from django.http import JsonResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from tree_engine.gedcom import parse

from .editing import EditError, create_person
from .importer import GedcomImportError, clear_tree, import_tree
from .models import FamilyTree

MAX_GEDCOM_BYTES = 30 * 1024 * 1024


def needs_start(tree: FamilyTree) -> bool:
    """Показывать ли окно первого входа: в древе ещё никого нет."""
    return not tree.people.exists()


def _refuse_if_started(tree: FamilyTree):
    if not needs_start(tree):
        return JsonResponse({"error": _("В древе уже есть люди. Импорт возможен только в пустое древо.")},
                            status=409)
    return None


def _done(tree: FamilyTree) -> JsonResponse:
    root = tree.root_person
    return JsonResponse({"redirect": reverse("tree") + (f"#{root.code}" if root else "")})


@require_POST
def start_self(request):
    """«Начать с нуля»: своя карточка. Все поля необязательны, как везде."""
    tree = FamilyTree.of(request.user)
    if refused := _refuse_if_started(tree):
        return refused
    data = {key: request.POST.get(key, "") for key in
            ("given_name", "patronymic", "birth_surname", "sex", "birth_date", "birth_place")}
    data["is_living"] = True
    clear_tree(tree)                 # остатки прежнего древа (места, материалы); номера — с P0001
    try:
        me = create_person(tree, data)
    except EditError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    tree.root_person = me
    tree.save(update_fields=["root_person"])
    return _done(tree)


def read_gedcom(upload) -> tuple[object, list[str]]:
    """Файл из формы → разобранное древо и предупреждения. Ошибки — понятным текстом (EditError)."""
    if upload is None:
        raise EditError(_("Выберите файл GEDCOM (.ged)."))
    if upload.size > MAX_GEDCOM_BYTES:
        raise EditError(_("Файл слишком большой (больше 30 МБ)."))
    raw = upload.read()
    notes = []
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        notes.append(_("Файл не в кодировке UTF-8: некоторые буквы могут отображаться неверно."))
    if "0 HEAD" not in text[:2000]:
        raise EditError(_("Это не похоже на GEDCOM: в начале файла нет заголовка «0 HEAD»."))
    tree = parse(text)
    if not tree.people:
        raise EditError(_("В файле не нашлось ни одного человека."))
    return tree, notes + tree.validate()


@require_POST
def start_gedcom(request):
    family_tree = FamilyTree.of(request.user)
    if refused := _refuse_if_started(family_tree):
        return refused
    try:
        tree, notes = read_gedcom(request.FILES.get("file"))
    except EditError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    if request.POST.get("action") == "import":
        clear_tree(family_tree)      # остатки прежнего древа; номера — с P0001
        try:
            import_tree(family_tree, tree, request.POST.get("root") or None)
        except GedcomImportError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        family_tree.refresh_from_db()
        return _done(family_tree)

    people = [{"gid": gid, "name": " ".join(x for x in (p.given, p.patronymic, p.surname) if x) or "?",
               "sex": p.sex, "years": p.years()} for gid, p in tree.people.items()]
    return JsonResponse({"people": people, "families": len(tree.families), "notes": notes[:5],
                         "notes_total": len(notes)})
