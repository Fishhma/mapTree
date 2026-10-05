from django.core.management import call_command
from django.test import TestCase

from .models import ParentChild, Partnership, Person, SiblingRelationship
from .views import build_graph


class GenealogyDemoTests(TestCase):
    def setUp(self):
        call_command("seed_data", verbosity=0)

    def test_seed_has_expected_normalized_shape(self):
        self.assertEqual(Person.objects.count(), 4)
        self.assertEqual(Partnership.objects.count(), 1)
        self.assertEqual(ParentChild.objects.count(), 4)
        self.assertEqual(ParentChild.objects.filter(partnership__isnull=False).count(), 4)

    def test_graph_endpoint_contains_nodes_and_relationships(self):
        response = self.client.get("/api/graph/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["people"]), 4)
        self.assertEqual(len(payload["partnerships"]), 1)
        self.assertEqual(len(payload["parent_child"]), 4)
        self.assertEqual(len(payload["siblings"]), 0)
        self.assertNotIn("x", payload["people"][0])
        self.assertEqual(len(build_graph()["people"]), 4)

    def test_person_record_can_be_updated(self):
        person = Person.objects.get(given_name="Iris")
        response = self.client.post(
            f"/api/people/{person.id}/",
            data={
                "given_name": "Iris",
                "family_name": "River",
                "birth_date": "2004-02-20",
                "death_date": "",
                "sex": "F",
                "notes": "Updated field note.",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        person.refresh_from_db()
        self.assertEqual(person.birth_date.isoformat(), "2004-02-20")
        self.assertEqual(person.notes, "Updated field note.")

    def test_add_person_creates_requested_relationship(self):
        anchor = Person.objects.get(given_name="Jonas")
        response = self.client.post(
            "/api/people/add/",
            data={
                "anchor_id": anchor.id,
                "relation": "parent",
                "given_name": "Arno",
                "family_name": "River",
                "birth_date": "1948-01-01",
                "death_date": "",
                "sex": "M",
                "notes": "",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        new_person = Person.objects.get(given_name="Arno")
        self.assertTrue(ParentChild.objects.filter(parent=new_person, child=anchor).exists())

    def test_add_child_can_select_a_specific_union(self):
        anchor = Person.objects.get(given_name="Jonas")
        union = Partnership.objects.get(partner_a=Person.objects.get(given_name="Mara"), partner_b=anchor)
        response = self.client.post(
            "/api/people/add/",
            data={
                "anchor_id": anchor.id,
                "relation": "child",
                "partnership_id": union.id,
                "given_name": "Nell",
                "family_name": "River",
                "birth_date": "",
                "death_date": "",
                "sex": "U",
                "notes": "",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        child = Person.objects.get(given_name="Nell")
        links = ParentChild.objects.filter(child=child, partnership=union)
        self.assertEqual(set(links.values_list("parent_id", flat=True)), {union.partner_a_id, union.partner_b_id})

    def test_add_sibling_uses_explicit_link_without_fabricating_parents(self):
        anchor = Person.objects.create(given_name="Solo", family_name="Root")
        response = self.client.post(
            "/api/people/add/",
            data={
                "anchor_id": anchor.id,
                "relation": "sibling",
                "given_name": "Sibling",
                "family_name": "Root",
                "birth_date": "",
                "death_date": "",
                "sex": "U",
                "notes": "",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        sibling = Person.objects.get(given_name="Sibling")
        self.assertFalse(ParentChild.objects.filter(child__in=[anchor, sibling]).exists())
        self.assertTrue(SiblingRelationship.objects.filter(person_a=anchor, person_b=sibling).exists())

    def test_graph_page_bootstraps_separately_loaded_modules(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="module"')
        self.assertContains(response, "kinship-graph-data")
        self.assertContains(response, "Collapse branches")
        content = response.content.decode()
        self.assertLess(content.index("Entire tree"), content.index('id="person-search"'))

    def test_invalid_union_does_not_leave_an_orphan_person(self):
        anchor = Person.objects.get(given_name="Iris")
        response = self.client.post(
            "/api/people/add/",
            data={
                "anchor_id": anchor.id,
                "relation": "child",
                "partnership_id": 999999,
                "given_name": "Orphan",
                "family_name": "River",
                "birth_date": "",
                "death_date": "",
                "sex": "U",
                "notes": "",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Person.objects.filter(given_name="Orphan").exists())
