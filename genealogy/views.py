from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from tree_engine.layout import compute_layout
from tree_engine.model import FuzzyDate
from tree_engine.render_svg import render as render_svg

from .bridge import build_tree, root_id, tree_payload
from .models import Event, Person


def tree_page(request):
    return render(request, "genealogy/tree.html")


def tree_api(request):
    return JsonResponse(tree_payload())


def tree_svg(request):
    """Всё древо одним SVG — для печати."""
    tree = build_tree()
    root = root_id(tree)
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
    years = ""
    if birth or death:
        start = FuzzyDate(birth.date).short() if birth and birth.date else "?"
        end = (FuzzyDate(death.date).short() if death.date else "†") if death else ""
        years = f"{start}–{end}"
    name = " ".join(x for x in (p.given_name, p.patronymic, p.birth_surname) if x) or "?"
    return {"id": str(p.pk), "code": p.code, "name": name, "sex": p.sex, "years": years}


def _event(e: Event):
    return {"kind": e.kind, "label": e.label, "date": e.date_display,
            "place": e.place.name if e.place else "", "value": e.value,
            "description": e.description}


def person_api(request, pk):
    person = get_object_or_404(
        Person.objects.prefetch_related("events__place", "names", "citations__source__files",
                                        "citations__event"), pk=pk)
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
        "deletion_blockers": person.deletion_blockers(),
        "admin_url": reverse("admin:genealogy_person_change", args=[person.pk]),
        "delete_url": reverse("admin:genealogy_person_delete", args=[person.pk]),
    })
    return JsonResponse(data)
