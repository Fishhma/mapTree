"""Тесты Django-части.  Запуск: python manage.py test"""
import unittest
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from .models import Event, Family, Person, Place, TreeSettings

GED = Path(__file__).resolve().parent.parent / "tests" / "rootsmagic_tree.ged"


def family(p1=None, p2=None, children=()):
    f = Family.objects.create(partner1=p1, partner2=p2)
    for c in children:
        c.parent_family = f
        c.save()
    return f


class SmallTreeMixin:
    """Дед → Libor (два брака: Ondřej от первого, Marian от второго) + дядя."""

    def make_tree(self):
        P = lambda name, sex="M": Person.objects.create(given_name=name, sex=sex)  # noqa: E731
        self.ded, self.libor, self.uncle = P("Дед"), P("Libor"), P("Дядя")
        self.wife1, self.julia = P("Жена 1", "F"), P("Юлия", "F")
        self.ondrej, self.marian = P("Ondřej"), P("Marian")
        family(self.ded, None, [self.libor, self.uncle])
        family(self.libor, self.wife1, [self.ondrej])
        family(self.libor, self.julia, [self.marian])
        Event.objects.create(person=self.ondrej, kind="BIRT", date="1986")
        Event.objects.create(person=self.marian, kind="BIRT", date="6.1.2007")
        s = TreeSettings.get()
        s.root_person = self.marian
        s.save()


class ModelTest(SmallTreeMixin, TestCase):
    def test_own_numbering(self):
        a, b = Person.objects.create(), Person.objects.create()
        self.assertRegex(a.code, r"^P\d{4}$")
        self.assertEqual(int(b.code[1:]), int(a.code[1:]) + 1)

    def test_person_without_any_data_is_allowed(self):
        p = Person.objects.create()
        self.assertEqual(p.given_name, "")
        self.assertIn("?", str(p))

    def test_dates_are_normalized_and_sorted(self):
        p = Person.objects.create()
        e = Event.objects.create(person=p, kind="BIRT", date="10.08.1962")
        self.assertEqual(e.date, "10 AUG 1962")
        self.assertEqual(e.date_display, "10 августа 1962")
        self.assertEqual(e.sort_key, 19620810)
        self.assertEqual(Event.objects.create(person=p, kind="DEAT", date="около 2030").date, "ABT 2030")

    def test_surname_change_does_not_break_anything(self):
        self.make_tree()
        self.marian.birth_surname = "Seková"
        self.marian.save()
        self.assertEqual(self.client.get("/api/tree/").status_code, 200)


class DeletionTest(SmallTreeMixin, TestCase):
    def setUp(self):
        self.make_tree()
        self.admin = User.objects.create_superuser("admin", "a@a.cz", "pw")
        self.client.force_login(self.admin)

    def test_blockers(self):
        self.assertTrue(self.libor.deletion_blockers())              # есть дети
        self.assertEqual(self.uncle.deletion_blockers(), [])         # один из нескольких детей
        self.assertEqual(self.ondrej.deletion_blockers(), [])

    def test_admin_refuses_blocked_delete(self):
        r = self.client.get(f"/admin/genealogy/person/{self.libor.pk}/delete/")
        self.assertEqual(r.status_code, 403)

    def test_admin_deletes_after_confirmation(self):
        url = f"/admin/genealogy/person/{self.uncle.pk}/delete/"
        self.assertEqual(self.client.get(url).status_code, 200)       # 1-е подтверждение
        self.client.post(url, {"post": "yes"})                        # 2-е подтверждение
        self.assertFalse(Person.objects.filter(pk=self.uncle.pk).exists())

    def test_empty_family_removed_after_deleting_childless_partner(self):
        lone = Person.objects.create(given_name="Бездетная")
        fam = family(self.uncle, lone)
        lone.delete()
        self.assertTrue(Family.objects.filter(pk=fam.pk).exists())   # дядя остался в семье
        self.uncle.delete()
        self.assertFalse(Family.objects.filter(pk=fam.pk).exists())  # семья опустела — удалена

    def test_admin_pages_open(self):
        for url in ["/admin/", "/admin/genealogy/person/", f"/admin/genealogy/person/{self.libor.pk}/change/",
                    "/admin/genealogy/family/", f"/admin/genealogy/family/{self.libor.families.first().pk}/change/",
                    "/admin/genealogy/source/add/", "/admin/genealogy/place/", "/admin/genealogy/treesettings/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)


class ApiTest(SmallTreeMixin, TestCase):
    def test_empty_tree(self):
        data = self.client.get("/api/tree/").json()
        self.assertEqual(data["boxes"], [])

    def test_tree_layout(self):
        self.make_tree()
        data = self.client.get("/api/tree/").json()
        self.assertEqual(len(data["boxes"]), 7)
        gen = {b["id"]: b["gen"] for b in data["boxes"]}
        self.assertEqual(gen[str(self.ondrej.pk)], gen[str(self.marian.pk)])   # одно поколение
        self.assertEqual(gen[str(self.marian.pk)], 1)
        self.assertEqual(data["root"], str(self.marian.pk))

    def test_person_card(self):
        self.make_tree()
        p = self.client.get(f"/api/people/{self.libor.pk}/").json()
        self.assertEqual(len(p["families"]), 2)
        self.assertEqual(p["parents"][0]["name"], "Дед")
        self.assertEqual(p["siblings"][0]["name"], "Дядя")
        self.assertTrue(p["deletion_blockers"])
        m = self.client.get(f"/api/people/{self.marian.pk}/").json()
        self.assertEqual(m["key"][0]["date"], "6 января 2007")

    def test_print_svg(self):
        self.make_tree()
        r = self.client.get("/tree.svg")
        self.assertEqual(r["Content-Type"], "image/svg+xml; charset=utf-8")
        self.assertIn(b"<svg", r.content)

    def test_page(self):
        self.assertContains(self.client.get("/"), "Найти человека")


class AddRelativeTest(SmallTreeMixin, TestCase):
    """«+» на карточке: POST /api/people/<pk>/add/."""

    def setUp(self):
        self.make_tree()

    def add(self, person, relation, **fields):
        return self.client.post(f"/api/people/{person.pk}/add/", {"relation": relation, **fields},
                                content_type="application/json")

    def new_person(self, response):
        self.assertEqual(response.status_code, 201, response.content)
        return Person.objects.get(pk=response.json()["id"])

    def test_child_into_chosen_marriage(self):
        second = Family.objects.get(partner1=self.libor, partner2=self.julia)
        kid = self.new_person(self.add(self.libor, "child", family=second.pk, given_name="Сводная",
                                       sex="F", birth_date="01.02.2010", birth_place="Brno"))
        self.assertEqual(kid.parent_family, second)
        self.assertRegex(kid.code, r"^P\d{4}$")
        birth = kid.events.get(kind="BIRT")
        self.assertEqual((birth.date, birth.place.name), ("1 FEB 2010", "Brno"))
        self.assertEqual(self.add(self.uncle, "child", birth_place="brno").status_code, 201)
        self.assertEqual(Place.objects.count(), 1)                 # место не задвоилось

    def test_child_without_family_gets_union_with_unknown_partner(self):
        kid = self.new_person(self.add(self.marian, "child"))
        fam = kid.parent_family
        self.assertEqual((fam.partner1, fam.partner2), (self.marian, None))

    def test_child_of_foreign_family_is_refused(self):
        foreign = Family.objects.get(partner1=self.ded)
        count = Person.objects.count()
        r = self.add(self.marian, "child", family=foreign.pk)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Person.objects.count(), count)            # ничего не создано

    def test_spouse_is_a_new_family(self):
        wife = self.new_person(self.add(self.libor, "spouse", given_name="Третья", sex="F"))
        self.assertEqual(self.libor.families.count(), 3)
        self.assertTrue(wife.families.filter(partner1=self.libor).exists())

    def test_parent_fills_free_slot_then_refuses(self):
        babka = self.new_person(self.add(self.libor, "parent", given_name="Бабка", sex="F"))
        fam = Person.objects.get(pk=self.libor.pk).parent_family
        self.assertEqual({fam.partner1, fam.partner2}, {self.ded, babka})
        self.assertEqual(self.uncle.parent_family_id, fam.pk)      # общая мать у братьев
        self.assertEqual(self.add(self.libor, "parent").status_code, 400)

    def test_parent_of_person_without_parents(self):
        father = self.new_person(self.add(self.ded, "parent", sex="M"))
        self.assertEqual(Person.objects.get(pk=self.ded.pk).parent_family.partner1, father)

    def test_sibling(self):
        sister = self.new_person(self.add(self.marian, "sibling", sex="F"))
        self.assertEqual(sister.parent_family_id, self.marian.parent_family_id)
        lone = self.new_person(self.add(self.ded, "sibling"))      # родители деда неизвестны
        fam = Person.objects.get(pk=self.ded.pk).parent_family
        self.assertEqual((fam.partners, lone.parent_family), ([], fam))
        self.assertEqual(len(self.client.get("/api/tree/").json()["boxes"]), 9)

    def test_bad_requests(self):
        self.assertEqual(self.add(self.marian, "cousin").status_code, 400)
        self.assertEqual(self.client.get(f"/api/people/{self.marian.pk}/add/").status_code, 405)
        r = self.client.post(f"/api/people/{self.marian.pk}/add/", "не json", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_csrf_is_required(self):
        from django.test import Client
        r = Client(enforce_csrf_checks=True).post(f"/api/people/{self.marian.pk}/add/", {"relation": "child"},
                                                 content_type="application/json")
        self.assertEqual(r.status_code, 403)


@unittest.skipUnless(GED.exists(), "нет tests/rootsmagic_tree.ged")
class ImportTest(TestCase):
    def test_import_real_file(self):
        call_command("import_gedcom", str(GED), root="@I1@", verbosity=0)
        self.assertEqual(Person.objects.count(), 108)
        self.assertEqual(Family.objects.count(), 47)
        root = TreeSettings.get().root_person
        self.assertEqual((root.given_name, root.birth_surname), ("Marian", "Hanus"))
        data = self.client.get("/api/tree/").json()
        self.assertEqual(len(data["boxes"]), 108)
        self.assertEqual(len(data["rows"]), 9)
