from datetime import datetime
import json

from django.http import JsonResponse
from django.db import transaction
from django.views.decorators.http import require_http_methods
from django.shortcuts import render

from .models import ParentChild, Partnership, Person, SiblingRelationship


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
    return {
        "people": [_person_payload(person) for person in people],
        "partnerships": [
            {
                "id": partnership.id,
                "partner_ids": [partnership.partner_a_id, partnership.partner_b_id],
                "start_date": _iso(partnership.start_date),
                "end_date": _iso(partnership.end_date),
                "label": partnership.label,
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
        "siblings": [
            {"id": link.id, "person_ids": [link.person_a_id, link.person_b_id], "label": link.label}
            for link in SiblingRelationship.objects.select_related("person_a", "person_b").all()
        ],
    }


def map_view(request):
    return render(request, "genealogy/map.html", {"graph": build_graph()})


def graph_data(request):
    return JsonResponse(build_graph())


@require_http_methods(["POST"])
def person_detail(request, person_id):
    try:
        person = Person.objects.get(pk=person_id)
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            return JsonResponse({"error": "Expected a person record object."}, status=400)
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
        if not isinstance(payload, dict):
            return JsonResponse({"error": "Expected a new person record object."}, status=400)
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
        partnership = None
        if relation == "child" and payload.get("partnership_id"):
            try:
                partnership = Partnership.objects.get(pk=int(payload["partnership_id"]))
            except (Partnership.DoesNotExist, TypeError, ValueError):
                raise ValueError("Choose a valid partnership.")
            if anchor.id not in (partnership.partner_a_id, partnership.partner_b_id):
                raise ValueError("Choose a partnership involving this person.")
        person = Person.objects.create(
            given_name=given_name, family_name=family_name, birth_date=birth_date,
            death_date=death_date, sex=payload["sex"], notes=(payload.get("notes") or "").strip(),
        )
        if relation == "spouse":
            Partnership.objects.create(partner_a=anchor, partner_b=person, label="")
        elif relation == "parent":
            ParentChild.objects.create(parent=person, child=anchor)
        elif relation == "child":
            parents = [anchor]
            if partnership:
                other_id = partnership.partner_b_id if partnership.partner_a_id == anchor.id else partnership.partner_a_id
                parents.append(Person.objects.get(pk=other_id))
            for parent in parents:
                ParentChild.objects.create(parent=parent, child=person, partnership=partnership)
        else:
            SiblingRelationship.objects.create(person_a=anchor, person_b=person)
        return JsonResponse({"person": _person_payload(person)})
    except Person.DoesNotExist:
        return JsonResponse({"error": "Anchor person not found."}, status=404)
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "Complete the new person record with valid values."}, status=400)
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)
