from django.core.management import call_command
from django.test import TestCase

from .models import ParentChild, Partnership, Person
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
