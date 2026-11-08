import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from tree_engine.layout import compute_layout
from tree_engine.model import FuzzyDate, lifespan
from tree_engine.render_svg import render as render_svg

from .bridge import build_tree, root_id, tree_payload
from .editing import (EditError, add_material, add_relative, delete_person, deletion_summary, error_text,
                      save_key_events)
from .forms import DATE_HINT, person_forms
from .models import Event, FamilyTree, Person, Place, Source
from .timeline import timeline

# Все страницы — только после входа (LoginRequiredMiddleware в настройках) и только
# со своим древом: человека из чужого древа не найти даже по прямой ссылке.


def user_tree(request) -> FamilyTree:
    tree, _ = FamilyTree.objects.get_or_create(owner=request.user)
    return tree


@ensure_csrf_cookie          # браузеру нужен CSRF-токен для добавления людей
def tree_page(request):
    return render(request, "genealogy/tree.html")


def tree_api(request):
    return JsonResponse(tree_payload(user_tree(request)))


def tree_svg(request):
    """Всё древо одним SVG — для печати."""
    family_tree = user_tree(request)
    tree = build_tree(family_tree)
    root = root_id(family_tree, tree)
    if root is None:
        return HttpResponse("Древо пустое", status=404)
    svg = render_svg(tree, compute_layout(tree, root), root=root)
    response = HttpResponse(svg, content_type="image/svg+xml; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="drevo.svg"'
    return response


def _brief(p: Person | None):
    if p is None:
        return None
    events = list(p.events.all())
    pick = lambda *kinds: next((e for k in kinds for e in events if e.kind == k), None)  # noqa: E731
    birth, death = pick("BIRT", "CHR"), pick("DEAT", "BURI")
    years = lifespan(FuzzyDate(birth.date) if birth and birth.date else None, death is not None,
                     FuzzyDate(death.date) if death and death.date else None, p.is_living)
    name = " ".join(x for x in (p.given_name, p.patronymic, p.birth_surname) if x) or "?"
    return {"id": str(p.pk), "code": p.code, "name": name, "sex": p.sex, "years": years}


def _event(e: Event):
    return {"kind": e.kind, "label": e.label, "date": e.date_display,
            "place": e.place.name if e.place else "", "value": e.value,
            "description": e.description}


def person_api(request, pk):
    person = get_object_or_404(
        Person.objects.prefetch_related("events__place", "names", "citations__source__files",
                                        "citations__event"), pk=pk, tree=user_tree(request))
    own = list(person.events.all())
    key = []
    for kind in ("BIRT", "CHR", "DEAT", "BURI"):
        found = [e for e in own if e.kind == kind]
        key.append(_event(found[0]) if found else
                   {"kind": kind, "label": Event.Kind(kind).label, "date": "", "place": "",
                    "value": "", "description": ""})
    families = []
    for fam in person.families.prefetch_related("events__place", "children__events"):
        spouse = fam.partner2 if fam.partner1_id == person.pk else fam.partner1
        families.append({
            "id": str(fam.pk),
            "spouse": _brief(spouse),
            "events": [_event(e) for e in fam.events.all()],
            "children": [_brief(c) for c in fam.children.all()],
        })
    parents, siblings = [], []
    if person.parent_family:
        pf = person.parent_family
        parents = [_brief(p) for p in (pf.partner1, pf.partner2) if p]
        siblings = [_brief(c) for c in pf.children.exclude(pk=person.pk)]
    sources = []
    for c in person.citations.all():
        s = c.source
        sources.append({
            "id": s.pk, "title": s.title, "kind": s.get_kind_display(), "date": s.date,
            "repository": s.repository, "reference": s.reference, "detail": c.detail,
            "event": c.event.label if c.event else "",
            "files": [{"url": f.file.url, "caption": f.caption or f.file.name.rsplit("/", 1)[-1],
                       "is_image": f.is_image} for f in s.files.all()],
            "admin_url": reverse("admin:genealogy_source_change", args=[s.pk]),
        })
    data = _brief(person)
    data.update({
        "given": person.given_name, "patronymic": person.patronymic,
        "surname": person.birth_surname, "sex_label": person.get_sex_display(),
        "notes": person.notes,
        "key": key,
        "events": [_event(e) for e in own if e.kind not in Event.KEY_KINDS | Event.FACT_KINDS],
        "facts": [_event(e) for e in own if e.kind in Event.FACT_KINDS],
        "names": [{"kind": n.get_kind_display(), "name": str(n), "date": n.date, "note": n.note}
                  for n in person.names.all()],
        "parents": parents, "siblings": siblings, "families": families, "sources": sources,
        "details_url": reverse("person-page", args=[person.code]),
    })
    return JsonResponse(data)


@require_POST
def add_relative_api(request, pk):
    """«+» на карточке: создать нового родственника. Тело — JSON с полями формы."""
    person = get_object_or_404(Person, pk=pk, tree=user_tree(request))
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "Неверный запрос."}, status=400)
    if not isinstance(body, dict):
        return JsonResponse({"error": "Неверный запрос."}, status=400)
    try:
        new = add_relative(person, body.get("relation"), body, body.get("family"))
    except (EditError, ValidationError) as exc:
        return JsonResponse({"error": error_text(exc)}, status=400)
    return JsonResponse({"id": str(new.pk), "code": new.code}, status=201)


def _person_context(person, forms_, notice="", notice_kind="info", delete_error=""):
    pf = person.parent_family
    families = []
    for fam in person.families.select_related("partner1", "partner2"):
        spouse = fam.partner2 if fam.partner1_id == person.pk else fam.partner1
        families.append({"spouse": spouse, "children": list(fam.children.all())})
    return {
        "person": person, **forms_,
        "years": _brief(person)["years"],
        "timeline": timeline(person),
        "parents": pf.partners if pf else [],
        "siblings": list(pf.children.exclude(pk=person.pk)) if pf else [],
        "families": families,
        "sources": materials(person, Source.Category.SOURCE),
        "memories": materials(person, Source.Category.MEMORY),
        "places": Place.objects.filter(tree=person.tree).values_list("name", flat=True),
        "date_hint": DATE_HINT,
        "blockers": person.deletion_blockers(),
        "summary": deletion_summary(person),
        "notice": notice, "notice_kind": notice_kind, "delete_error": delete_error,
    }


def materials(person, category) -> list[dict]:
    """Источники или воспоминания человека по дате события; у каждого — кто ещё к нему привязан."""
    items, seen = [], set()
    citations = person.citations.filter(source__category=category).select_related("source") \
        .prefetch_related("source__files", "source__citations__person")
    for c in citations:
        source = c.source
        if source.pk in seen:
            continue
        seen.add(source.pk)
        files = list(source.files.all())
        others = {x.person_id: x.person for x in source.citations.all() if x.person_id != person.pk}
        items.append({"source": source, "image": next((f for f in files if f.is_image), None),
                      "files": files, "others": list(others.values())})
    items.sort(key=lambda i: (i["source"].sort_key, i["source"].title.lower()))
    return items


MATERIAL_TABS = {Source.Category.SOURCE: ("sources", "_person_sources.html"),
                 Source.Category.MEMORY: ("memories", "_person_memories.html")}


@require_POST
def add_material_view(request, code):
    """«Добавить» во вкладке «Источники» или «Воспоминания»: изображение, название, дата события."""
    person = get_object_or_404(Person, code=code, tree=user_tree(request))
    category = request.POST.get("category", "")
    is_fetch = request.headers.get("X-Requested-With") == "fetch"
    try:
        source, existed = add_material(person, category, request.FILES.get("file"),
                                       request.POST.get("title", ""), request.POST.get("date", ""))
    except EditError as exc:
        if is_fetch:
            return JsonResponse({"status": "error", "message": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect(reverse("person-page", args=[code]) + "#" + MATERIAL_TABS.get(category, ("about",))[0])
    notice = (f"Такой файл уже есть: «{source.title}». Он привязан к этому человеку."
              if existed else f"Добавлено: «{source.title}».")
    tab, template = MATERIAL_TABS[category]
    if not is_fetch:
        messages.success(request, notice)
        return redirect(reverse("person-page", args=[code]) + "#" + tab)
    items = materials(person, category)
    html = render_to_string(f"genealogy/{template}",
                            {"person": person, tab: items, "notice": notice, "date_hint": DATE_HINT}, request)
    return JsonResponse({"status": "success", "tab": tab, "count": len(items), "html": html})


def _save_person(person, forms_) -> str:
    """Сохранить все формы страницы. Возвращает текст для уведомления."""
    if not any(f.has_changed() for f in forms_.values()):
        return "Изменений нет."
    with transaction.atomic():
        forms_["form"].save()
        save_key_events(person, forms_["events_form"].events, forms_["events_form"].cleaned_data)
        forms_["other_events"].save()
        forms_["names"].save()
    return "Изменения сохранены."


def person_page(request, code):
    """Страница человека: вкладки «О человеке», «Источники», «Воспоминания».

    Правка и удаление — только здесь. Браузер отправляет формы через fetch
    (заголовок X-Requested-With: fetch) и получает обратно готовый HTML вкладки,
    поэтому в истории браузера не копятся одинаковые страницы. Без JS работает
    обычная отправка формы с переадресацией.
    """
    person = get_object_or_404(Person, code=code, tree=user_tree(request))
    is_fetch = request.headers.get("X-Requested-With") == "fetch"
    forms_ = person_forms(person)
    notice, notice_kind, delete_error = "", "info", ""

    if request.method == "POST" and request.POST.get("action") == "delete":
        try:
            delete_person(person, request.POST.get("confirm_code", ""))
        except EditError as exc:
            if is_fetch:
                return JsonResponse({"status": "error", "message": str(exc)}, status=400)
            delete_error = str(exc)
        else:
            messages.success(request, f"{person.code} удалён(а).")
            if is_fetch:
                return JsonResponse({"status": "deleted", "redirect": reverse("tree")})
            return redirect("tree")
    elif request.method == "POST":
        bound = person_forms(person, request.POST)
        if all(f.is_valid() for f in bound.values()):
            notice = _save_person(person, bound)
            notice_kind = "success" if notice == "Изменения сохранены." else "info"
            if not is_fetch:
                messages.add_message(request, messages.SUCCESS if notice_kind == "success" else messages.INFO,
                                     notice)
                return redirect("person-page", code=person.code)
            person.refresh_from_db()
            forms_ = person_forms(person)
        else:
            forms_, notice, notice_kind = bound, "Проверьте выделенные поля.", "error"

    context = _person_context(person, forms_, notice, notice_kind, delete_error)
    if is_fetch:
        return JsonResponse({
            "status": notice_kind,
            "header": render_to_string("genealogy/_person_header.html", context, request),
            "about": render_to_string("genealogy/_person_about.html", context, request),
        }, status=400 if notice_kind == "error" else 200)
    return render(request, "genealogy/person.html", context)
