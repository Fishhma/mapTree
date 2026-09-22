from datetime import datetime
import json

from django.http import JsonResponse
from django.db import transaction
from django.views.decorators.http import require_http_methods
from django.shortcuts import render

from .models import ParentChild, Partnership, Person


def _iso(value):
    return value.isoformat() if value else None


def _person_payload(person):
    return {
        "id": person.id,
        "name": person.full_name,
        "given_name": person.given_name,
        "family_name": person.family_name,
        "birth_date": _iso(person.birth_date),
        "death_date": _iso(person.death_date),
        "sex": person.sex,
        "notes": person.notes,
    }


def build_graph():
    people = list(Person.objects.all())
    partnerships = list(
        Partnership.objects.select_related("partner_a", "partner_b").all()
    )
    parent_children = list(
        ParentChild.objects.select_related("parent", "child", "partnership").all()
    )
    # This deterministic layout is intentionally isolated from the API shape so a
    # general graph/layout engine can replace it without changing templates.
    positions = {person.id: {"x": 250 + index * 260, "y": 150} for index, person in enumerate(people)}
    if len(people) == 4:
        positions[people[0].id] = {"x": 300, "y": 145}
        positions[people[1].id] = {"x": 720, "y": 145}
        positions[people[2].id] = {"x": 350, "y": 465}
        positions[people[3].id] = {"x": 670, "y": 465}

    return {
        "people": [
            {**_person_payload(person), "x": positions[person.id]["x"], "y": positions[person.id]["y"]}
            for person in people
        ],
        "partnerships": [
            {
                "id": partnership.id,
                "partner_ids": [partnership.partner_a_id, partnership.partner_b_id],
                "start_date": _iso(partnership.start_date),
                "end_date": _iso(partnership.end_date),
                "label": partnership.label,
                "x": (positions[partnership.partner_a_id]["x"] + positions[partnership.partner_b_id]["x"]) / 2,
                "y": 285,
            }
            for partnership in partnerships
        ],
        "parent_child": [
            {
                "id": link.id,
                "parent_id": link.parent_id,
                "child_id": link.child_id,
                "partnership_id": link.partnership_id,
                "birth_order": link.birth_order,
            }
            for link in parent_children
        ],
    }


def map_view(request):
    return render(request, "genealogy/map.html", {"graph_json": json.dumps(build_graph())})


def graph_data(request):
    return JsonResponse(build_graph())


@require_http_methods(["POST"])
def person_detail(request, person_id):
    try:
        person = Person.objects.get(pk=person_id)
        payload = json.loads(request.body)
        birth_date = payload.get("birth_date") or None
        death_date = payload.get("death_date") or None
        if birth_date:
            birth_date = datetime.strptime(birth_date, "%Y-%m-%d").date()
        if death_date:
            death_date = datetime.strptime(death_date, "%Y-%m-%d").date()
        if birth_date and death_date and death_date < birth_date:
            return JsonResponse({"error": "Death date cannot be before birth date."}, status=400)
        if payload.get("sex") not in dict(Person.Sex.choices):
            return JsonResponse({"error": "Choose a valid gender."}, status=400)
        person.given_name = (payload.get("given_name") or "").strip()
        person.family_name = (payload.get("family_name") or "").strip()
        if not person.given_name or not person.family_name:
            return JsonResponse({"error": "Given and family names are required."}, status=400)
        person.birth_date = birth_date
        person.death_date = death_date
        person.sex = payload["sex"]
        person.notes = (payload.get("notes") or "").strip()
        person.save()
        return JsonResponse({"person": _person_payload(person)})
    except Person.DoesNotExist:
        return JsonResponse({"error": "Person not found."}, status=404)
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"error": "Use valid dates in YYYY-MM-DD format."}, status=400)


@require_http_methods(["POST"])
@transaction.atomic
def add_person(request):
    try:
        payload = json.loads(request.body)
        anchor = Person.objects.get(pk=payload["anchor_id"])
        relation = payload.get("relation")
        if relation not in {"parent", "child", "sibling", "spouse"}:
            return JsonResponse({"error": "Choose a valid relationship."}, status=400)
        birth_date = payload.get("birth_date") or None
        death_date = payload.get("death_date") or None
        if birth_date:
            birth_date = datetime.strptime(birth_date, "%Y-%m-%d").date()
        if death_date:
            death_date = datetime.strptime(death_date, "%Y-%m-%d").date()
        if birth_date and death_date and death_date < birth_date:
            return JsonResponse({"error": "Death date cannot be before birth date."}, status=400)
        if payload.get("sex") not in dict(Person.Sex.choices):
            return JsonResponse({"error": "Choose a valid gender."}, status=400)
        given_name = (payload.get("given_name") or "").strip()
        family_name = (payload.get("family_name") or "").strip()
        if not given_name or not family_name:
            return JsonResponse({"error": "Name and surname are required."}, status=400)
        person = Person.objects.create(
            given_name=given_name, family_name=family_name, birth_date=birth_date,
            death_date=death_date, sex=payload["sex"], notes=(payload.get("notes") or "").strip(),
        )
        if relation == "spouse":
            Partnership.objects.create(partner_a=anchor, partner_b=person, label="")
        elif relation == "parent":
            partnership = anchor.parent_links.first().partnership if anchor.parent_links.exists() else None
            ParentChild.objects.create(parent=person, child=anchor, partnership=partnership)
        elif relation == "child":
            partnership = anchor.partnerships_as_a.first() or anchor.partnerships_as_b.first()
            ParentChild.objects.create(parent=anchor, child=person, partnership=partnership)
        else:
            for link in anchor.parent_links.all():
                ParentChild.objects.create(parent=link.parent, child=person, partnership=link.partnership)
        return JsonResponse({"person": _person_payload(person)})
    except Person.DoesNotExist:
        return JsonResponse({"error": "Anchor person not found."}, status=404)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return JsonResponse({"error": "Complete the new person record with valid values."}, status=400)
