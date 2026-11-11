"""Тесты Django-части.  Запуск: python manage.py test"""
import unittest
from pathlib import Path

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone

from .models import Event, Family, FamilyTree, Invitation, Person, Place, Source, SourceFile

GED = Path(__file__).resolve().parent.parent / "tests" / "rootsmagic_tree.ged"


def family(p1=None, p2=None, children=()):
    tree = next(x.tree for x in (p1, p2, *children) if x)
    f = Family.objects.create(tree=tree, partner1=p1, partner2=p2)
    for c in children:
        c.parent_family = f
        c.save()
    return f


class SmallTreeMixin:
    """Владелец древа уже вошёл на сайт. make_tree():
    Дед → Libor (два брака: Ondřej от первого, Marian от второго) + дядя."""

    def setUp(self):
        self.user = User.objects.create_user("owner", password="Древо-пароль-1")
        self.tree = FamilyTree.objects.create(owner=self.user)
        self.client.force_login(self.user)

    def person(self, **fields):
        return Person.objects.create(tree=self.tree, **fields)

    def make_tree(self):
        P = lambda name, sex="M": self.person(given_name=name, sex=sex)  # noqa: E731
        self.ded, self.libor, self.uncle = P("Дед"), P("Libor"), P("Дядя")
        self.wife1, self.julia = P("Жена 1", "F"), P("Юлия", "F")
        self.ondrej, self.marian = P("Ondřej"), P("Marian")
        family(self.ded, None, [self.libor, self.uncle])
        family(self.libor, self.wife1, [self.ondrej])
        family(self.libor, self.julia, [self.marian])
        Event.objects.create(person=self.ondrej, kind="BIRT", date="1986")
        Event.objects.create(person=self.marian, kind="BIRT", date="6.1.2007")
        self.tree.root_person = self.marian
        self.tree.save()


class ModelTest(SmallTreeMixin, TestCase):
    def test_own_numbering(self):
        a, b = self.person(), self.person()
        self.assertRegex(a.code, r"^P\d{4}$")
        self.assertEqual(int(b.code[1:]), int(a.code[1:]) + 1)

    def test_person_without_any_data_is_allowed(self):
        p = self.person()
        self.assertEqual(p.given_name, "")
        self.assertIn("?", str(p))

    def test_dates_are_normalized_and_sorted(self):
        p = self.person()
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
        super().setUp()
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

    def test_hollow_family_removed_after_deleting_childless_partner(self):
        # Случай Josef Maňas: удалили бездетную жену — от брака не должен остаться отросток.
        lone = self.person(given_name="Бездетная")
        fam = family(self.uncle, lone)
        lone.delete()
        self.assertFalse(Family.objects.filter(pk=fam.pk).exists())

    def test_family_with_children_survives_partner_deletion(self):
        ded_family = self.libor.parent_family
        self.ded.delete()                                            # родоначальник: выше никого
        ded_family.refresh_from_db()
        self.assertEqual(ded_family.children.count(), 2)            # Libor и дядя остались братьями

    def test_migration_cleanup_function_removes_only_hollow_families(self):
        from .signals import drop_hollow_families
        hollow = family(self.uncle)                                 # один партнёр, без детей
        kept = family(self.uncle, None, [self.person()])  # один партнёр, но есть ребёнок
        self.assertEqual(drop_hollow_families(), 1)
        self.assertFalse(Family.objects.filter(pk=hollow.pk).exists())
        self.assertTrue(Family.objects.filter(pk=kept.pk).exists())

    def test_admin_pages_open(self):
        for url in ["/admin/", "/admin/genealogy/person/", f"/admin/genealogy/person/{self.libor.pk}/change/",
                    "/admin/genealogy/family/", f"/admin/genealogy/family/{self.libor.families.first().pk}/change/",
                    "/admin/genealogy/source/add/", "/admin/genealogy/place/", "/admin/genealogy/familytree/",
                    "/admin/genealogy/invitation/", "/admin/genealogy/invitation/add/"]:
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
        self.assertEqual(p["details_url"], f"/people/{self.libor.code}/")
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
        super().setUp()
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
        kid = self.new_person(self.add(self.marian, "child", is_living="on"))
        self.assertTrue(kid.is_living)
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

    def test_spouse_becomes_other_parent_of_children(self):
        # Случай Maňas: у Josef дочь, мать неизвестна; добавляем жену как её мать.
        josef, renata = self.person(given_name="Josef"), self.person(given_name="Renata")
        fam = family(josef, None, [renata])
        tatana = self.new_person(self.add(josef, "spouse", family=fam.pk, given_name="Taťána", sex="F"))
        fam.refresh_from_db()
        self.assertEqual((fam.partner1, fam.partner2), (josef, tatana))
        self.assertEqual(josef.families.count(), 1)                # новой семьи не появилось
        tree = self.client.get("/api/tree/").json()
        self.assertEqual(sorted(tree["families"][str(fam.pk)]["partners"]), sorted([str(josef.pk), str(tatana.pk)]))
        self.assertEqual(tree["families"][str(fam.pk)]["children"], [str(renata.pk)])

    def test_spouse_fills_first_slot_if_person_is_second(self):
        mother, kid = self.person(given_name="Мать"), self.person(given_name="Ребёнок")
        fam = family(None, mother, [kid])
        father = self.new_person(self.add(mother, "spouse", family=fam.pk))
        fam.refresh_from_db()
        self.assertEqual((fam.partner1, fam.partner2), (father, mother))

    def test_spouse_as_new_marriage_when_family_not_chosen(self):
        josef, renata = self.person(given_name="Josef"), self.person(given_name="Renata")
        fam = family(josef, None, [renata])
        self.new_person(self.add(josef, "spouse", family=""))
        self.assertEqual(josef.families.count(), 2)
        fam.refresh_from_db()
        self.assertIsNone(fam.partner2)                            # у дочери мать по-прежнему неизвестна

    def test_spouse_into_full_or_foreign_family_is_refused(self):
        count = Person.objects.count()
        full = Family.objects.get(partner1=self.libor, partner2=self.julia)
        self.assertEqual(self.add(self.libor, "spouse", family=full.pk).status_code, 400)
        foreign = Family.objects.get(partner1=self.ded)
        self.assertEqual(self.add(self.libor, "spouse", family=foreign.pk).status_code, 400)
        self.assertEqual(Person.objects.count(), count)            # ничего не создано

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
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        r = client.post(f"/api/people/{self.marian.pk}/add/", {"relation": "child"},
                                                 content_type="application/json")
        self.assertEqual(r.status_code, 403)


class PersonPageTest(SmallTreeMixin, TestCase):
    """Страница /people/P0001/: вкладки, правка и удаление только здесь."""

    def setUp(self):
        super().setUp()
        self.make_tree()

    def url(self, person):
        return f"/people/{person.code}/"

    def page_data(self, person, **changes):
        """Что браузер отправит, если ничего не трогать; changes правят поля (None — убрать поле)."""
        from .forms import person_forms
        data = {}
        for f in person_forms(Person.objects.get(pk=person.pk)).values():
            parts = [f.management_form, *f.forms] if hasattr(f, "management_form") else [f]
            for form in parts:
                for bound in form:
                    value = bound.value()
                    if value is not None and value is not False and value != "":
                        data[bound.html_name] = value
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        return data

    def save(self, person, follow=False, fetch=False, **changes):
        headers = {"X-Requested-With": "fetch"} if fetch else {}
        return self.client.post(self.url(person), self.page_data(person, **changes), follow=follow,
                                headers=headers)

    def test_page_shows_person_and_family(self):
        r = self.client.get(self.url(self.libor))
        self.assertContains(r, "Libor")
        self.assertContains(r, self.url(self.marian))              # ссылка на ребёнка
        self.assertContains(r, "Удалить нельзя")                    # у Libor есть и отец, и дети
        for tab in ("О человеке", 'Источники (<span data-count="sources">0</span>)',
                    'Воспоминания (<span data-count="memories">0</span>)'):
            self.assertContains(r, tab)
        self.assertEqual(self.client.get("/people/P9999/").status_code, 404)

    def test_marian_birth_date_shown_in_user_format(self):
        self.assertContains(self.client.get(self.url(self.marian)), 'value="06.01.2007"')

    def test_timeline_has_own_events_marriages_and_children(self):
        Event.objects.create(family=self.libor.families.get(partner2=self.julia), kind="MARR", date="2005")
        titles = [t["title"] for t in self.client.get(self.url(self.libor)).context["timeline"]]
        self.assertEqual(titles, ["Рождение сына", "Брак", "Рождение сына", "Брак"])   # 1986, 2005, 2007, без даты

    def test_save_fields_and_key_events(self):
        r = self.save(self.uncle, given_name="Дядя Ваня", patronymic="Петрович", sex="M",
                      BIRT_date="около 1950", BIRT_place="Brno", DEAT_date="2.3.2020", notes="Жил долго.")
        self.assertRedirects(r, self.url(self.uncle))
        uncle = Person.objects.get(pk=self.uncle.pk)
        self.assertEqual((uncle.given_name, uncle.patronymic, uncle.notes),
                         ("Дядя Ваня", "Петрович", "Жил долго."))
        self.assertEqual(uncle.events.get(kind="BIRT").date, "ABT 1950")
        self.assertEqual(uncle.events.get(kind="BIRT").place.name, "Brno")
        self.assertEqual(uncle.events.get(kind="DEAT").date, "2 MAR 2020")

    def test_clearing_key_event_removes_it(self):
        self.save(self.ondrej, BIRT_date=None)                     # дату рождения стёрли
        self.assertFalse(self.ondrej.events.filter(kind="BIRT").exists())

    def test_cleared_event_with_description_is_kept(self):
        Event.objects.filter(person=self.ondrej, kind="BIRT").update(description="в роддоме")
        self.save(self.ondrej, BIRT_date=None)
        self.assertEqual(self.ondrej.events.get(kind="BIRT").date, "")

    def test_save_without_changes_says_so(self):
        self.assertContains(self.save(self.marian, follow=True), "Изменений нет")
        self.assertContains(self.save(self.marian, given_name="Мариан", follow=True), "Изменения сохранены")

    def test_fetch_save_returns_fragments_without_redirect(self):
        r = self.save(self.marian, fetch=True, given_name="Мариан")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("Изменения сохранены", data["about"])
        self.assertIn("Мариан", data["header"])
        r = self.save(self.marian, fetch=True)
        self.assertIn("Изменений нет", r.json()["about"])

    def test_other_events_and_names(self):
        r = self.save(self.marian, **{
            "events-TOTAL_FORMS": "1", "events-0-kind": "RESI", "events-0-date": "2010-2015",
            "events-0-place_name": "Praha", "events-0-description": "с мамой",
            "names-TOTAL_FORMS": "1", "names-0-kind": "translit", "names-0-given_name": "Мариан"})
        self.assertRedirects(r, self.url(self.marian))
        resi = self.marian.events.get(kind="RESI")
        self.assertEqual((resi.date, resi.place.name, resi.description), ("BET 2010 AND 2015", "Praha", "с мамой"))
        self.assertEqual(self.marian.names.get().given_name, "Мариан")
        page = self.client.get(self.url(self.marian))
        self.assertContains(page, 'value="между 2010 и 2015"')
        self.assertContains(page, "Место жительства")             # и в хронологии
        self.save(self.marian, **{"events-0-DELETE": "on", "names-0-DELETE": "on"})
        self.assertFalse(self.marian.events.filter(kind="RESI").exists())
        self.assertFalse(self.marian.names.exists())

    def test_invalid_row_is_reported(self):
        r = self.save(self.marian, fetch=True, **{"events-TOTAL_FORMS": "1", "events-0-date": "1990"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Проверьте выделенные поля", r.json()["about"])
        self.assertFalse(self.marian.events.exclude(kind="BIRT").exists())

    def test_living_flag_changes_years(self):
        self.save(self.ondrej, is_living="on")
        self.assertEqual(self.client.get(f"/api/people/{self.ondrej.pk}/").json()["years"], "1986–")
        self.save(self.ondrej, is_living=None)
        self.assertEqual(self.client.get(f"/api/people/{self.ondrej.pk}/").json()["years"], "1986–?")

    def test_top_ancestor_can_be_deleted(self):
        r = self.client.get(self.url(self.ded))
        self.assertNotContains(r, "Удалить нельзя")
        self.client.post(self.url(self.ded), {"action": "delete", "confirm_code": self.ded.code})
        self.assertFalse(Person.objects.filter(pk=self.ded.pk).exists())
        libor = Person.objects.get(pk=self.libor.pk)
        self.assertEqual(libor.parent_family_id, self.uncle.parent_family_id)   # братья остались братьями

    def test_delete_needs_exact_code(self):
        r = self.client.post(self.url(self.uncle), {"action": "delete", "confirm_code": "P0000"})
        self.assertContains(r, "Номер не совпадает")
        self.assertTrue(Person.objects.filter(pk=self.uncle.pk).exists())
        r = self.client.post(self.url(self.uncle), {"action": "delete",
                                                    "confirm_code": self.uncle.code.lower()})
        self.assertRedirects(r, "/")
        self.assertFalse(Person.objects.filter(pk=self.uncle.pk).exists())

    def test_fetch_delete(self):
        url, fetch = self.url(self.uncle), {"X-Requested-With": "fetch"}
        r = self.client.post(url, {"action": "delete", "confirm_code": "x"}, headers=fetch)
        self.assertEqual((r.status_code, r.json()["status"]), (400, "error"))
        r = self.client.post(url, {"action": "delete", "confirm_code": self.uncle.code}, headers=fetch)
        self.assertEqual(r.json(), {"status": "deleted", "redirect": "/"})

    def test_blocked_person_cannot_be_deleted(self):
        r = self.client.post(self.url(self.libor), {"action": "delete", "confirm_code": self.libor.code})
        self.assertContains(r, "Удалить нельзя")
        self.assertTrue(Person.objects.filter(pk=self.libor.pk).exists())

    def test_tree_page_has_no_admin_button(self):
        self.assertNotContains(self.client.get("/"), "/admin/")


class MaterialsTest(SmallTreeMixin, TestCase):
    """«Добавить» в «Источниках» и «Воспоминаниях»: изображение + название + дата."""

    def setUp(self):
        import shutil
        import tempfile
        from django.test import override_settings
        super().setUp()
        self.make_tree()
        media = tempfile.mkdtemp()                     # файлы тестов — не в настоящий media/
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)

    def upload(self, person, category="memory", name="svadba.jpg", content=b"jpeg-bytes", **fields):
        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {"category": category, "file": SimpleUploadedFile(name, content), **fields}
        return self.client.post(f"/people/{person.code}/materials/", data, headers={"X-Requested-With": "fetch"})

    def test_add_memory_with_title_and_date(self):
        r = self.upload(self.marian, title="Свадьба Игнаца", date="12.05.1890")
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertEqual((data["tab"], data["count"]), ("memories", 1))
        self.assertIn("Свадьба Игнаца", data["html"])
        self.assertIn("12 мая 1890", data["html"])
        source = Source.objects.get()
        self.assertEqual((source.category, source.date, source.kind), ("memory", "12 MAY 1890", "photo"))
        self.assertTrue(source.files.get().sha256)
        page = self.client.get(f"/people/{self.marian.code}/")
        self.assertEqual(len(page.context["memories"]), 1)
        self.assertEqual(len(page.context["sources"]), 0)

    def test_title_defaults_to_file_name(self):
        self.upload(self.marian, category="source", name="Narozeni Anna 1890.png")
        self.assertEqual(Source.objects.get().title, "Narozeni Anna 1890")

    def test_same_file_is_stored_once_and_shared(self):
        self.upload(self.marian, title="Семейное фото")
        r = self.upload(self.ondrej, name="kopie.jpg")                    # тот же файл, другое имя
        self.assertIn("уже есть", r.json()["html"])
        self.assertEqual(Source.objects.count(), 1)
        self.assertEqual(SourceFile.objects.count(), 1)
        self.assertEqual(Source.objects.get().citations.count(), 2)
        page = self.client.get(f"/people/{self.ondrej.code}/")
        self.assertContains(page, "Также у:")
        self.assertContains(page, self.marian.full_name)

    def test_only_images_are_accepted(self):
        r = self.upload(self.marian, name="dopis.pdf")
        self.assertEqual((r.status_code, r.json()["status"]), (400, "error"))
        r = self.client.post(f"/people/{self.marian.code}/materials/", {"category": "memory"},
                             headers={"X-Requested-With": "fetch"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Source.objects.exists())

    def test_page_has_add_buttons_and_delete_block_at_bottom(self):
        html = self.client.get(f"/people/{self.uncle.code}/").content.decode()
        self.assertEqual(html.count("data-add-material"), 2)
        self.assertGreater(html.index("danger-zone"), html.index("about-side"))


@unittest.skipUnless(GED.exists(), "нет tests/rootsmagic_tree.ged")
class ImportTest(SmallTreeMixin, TestCase):
    def test_import_real_file(self):
        call_command("import_gedcom", str(GED), user="owner", root="@I1@", verbosity=0)
        self.assertEqual(Person.objects.filter(tree=self.tree).count(), 108)
        self.assertEqual(Family.objects.filter(tree=self.tree).count(), 47)
        self.tree.refresh_from_db()
        root = self.tree.root_person
        self.assertEqual((root.given_name, root.birth_surname, root.code), ("Marian", "Hanus", "P0001"))
        data = self.client.get("/api/tree/").json()
        self.assertEqual(len(data["boxes"]), 108)
        self.assertEqual(len(data["rows"]), 9)


class SeparateTreesTest(SmallTreeMixin, TestCase):
    """У каждого пользователя своё древо: чужих людей не видно даже по прямой ссылке."""

    def setUp(self):
        super().setUp()
        self.make_tree()
        self.other = User.objects.create_user("guest", password="Древо-пароль-2")
        self.other_tree = FamilyTree.objects.create(owner=self.other)
        self.stranger = Person.objects.create(tree=self.other_tree, given_name="Чужой")

    def test_login_required_everywhere(self):
        anon = Client()
        for url in ["/", "/api/tree/", f"/api/people/{self.libor.pk}/", f"/people/{self.libor.code}/",
                    "/tree.svg"]:
            r = anon.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertTrue(r["Location"].startswith("/login/"), url)
        self.assertContains(anon.get("/login/"), "Вход")

    def test_numbering_is_per_tree_and_not_reused(self):
        self.assertEqual(self.libor.code[:1], "P")
        self.assertEqual(self.stranger.code, "P0001")                 # своя нумерация у второго древа
        codes = sorted(Person.objects.filter(tree=self.tree).values_list("code", flat=True))
        self.assertEqual(codes, [f"P{i:04d}" for i in range(1, 8)])
        self.ondrej.delete()                                          # P0006
        self.assertEqual(self.person().code, "P0008")                 # номер удалённого не занимается

    def test_other_users_people_are_invisible(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f"/people/{self.libor.code}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/people/{self.libor.pk}/").status_code, 404)
        r = self.client.post(f"/api/people/{self.libor.pk}/add/", {"relation": "child"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 404)
        data = self.client.get("/api/tree/").json()
        self.assertEqual([b["id"] for b in data["boxes"]], [str(self.stranger.pk)])
        self.assertContains(self.client.get(f"/people/{self.stranger.code}/"), "Чужой")

    def test_same_place_name_in_two_trees(self):
        from .editing import find_or_create_place
        a = find_or_create_place(self.tree, "Brno")
        b = find_or_create_place(self.other_tree, "brno")
        self.assertNotEqual(a.pk, b.pk)
        self.assertEqual(find_or_create_place(self.tree, "BRNO"), a)

    def test_logout(self):
        r = self.client.post("/logout/")
        self.assertRedirects(r, "/login/")
        self.assertEqual(self.client.get("/").status_code, 302)


class InvitationTest(TestCase):
    """Регистрация — только по одноразовой ссылке-приглашению."""

    def setUp(self):
        self.invitation = Invitation.objects.create(note="Для мамы")
        self.url = f"/invite/{self.invitation.code}/"

    def register(self, client=None, username="mama", language="ru"):
        return (client or self.client).post(self.url, {"username": username, "password1": "Velka-rodina-1890",
                                                       "password2": "Velka-rodina-1890", "language": language})

    def test_registration_creates_user_with_own_empty_tree(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Регистрация")
        self.assertContains(page, "Логин")
        r = self.register()
        self.assertRedirects(r, "/")
        user = User.objects.get(username="mama")
        self.assertEqual(user.family_tree.people.count(), 0)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.used_by, user)
        self.assertEqual(self.client.get("/").status_code, 200)       # уже вошла

    def test_link_works_only_once(self):
        self.register()
        r = self.register(Client(), username="kdo-jiny")
        self.assertContains(r, "уже зарегистрировались", status_code=404)
        self.assertFalse(User.objects.filter(username="kdo-jiny").exists())

    def test_expired_and_unknown_links(self):
        Invitation.objects.filter(pk=self.invitation.pk).update(expires=timezone.now() - timedelta(days=1))
        self.assertContains(self.client.get(self.url), "Срок действия", status_code=404)
        self.assertContains(self.client.get("/invite/nesmysl/"), "Такой ссылки нет", status_code=404)

    def test_weak_password_is_refused(self):
        r = self.client.post(self.url, {"username": "mama", "password1": "12345678", "password2": "12345678"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="mama").exists())

    def test_signed_in_user_cannot_use_invitation(self):
        self.client.force_login(User.objects.create_user("owner", password="x"))
        self.assertContains(self.client.get(self.url), "Вы уже вошли", status_code=400)

    def test_admin_shows_copyable_link(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@a.cz", "pw"))
        r = self.client.get(f"/admin/genealogy/invitation/{self.invitation.pk}/change/")
        self.assertContains(r, f"http://testserver/invite/{self.invitation.code}/")


class MigrationTest(TransactionTestCase):
    """Перенос прежних данных в древо первого администратора (0005_family_trees)."""

    before = [("genealogy", "0004_drop_hollow_families")]
    after = [("genealogy", "0005_family_trees")]

    def test_existing_data_becomes_tree_of_first_superuser(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old = executor.loader.project_state(self.before).apps
        admin = User.objects.create(username="admin", is_superuser=True)
        Person = old.get_model("genealogy", "Person")
        marian = Person.objects.create(code="P0001", given_name="Marian")
        Person.objects.create(code="P0007")
        old.get_model("genealogy", "Place").objects.create(name="Brno")
        old.get_model("genealogy", "TreeSettings").objects.create(pk=1, root_person=marian)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        new = executor.loader.project_state(self.after).apps
        tree = new.get_model("genealogy", "FamilyTree").objects.get()
        self.assertEqual((tree.owner_id, tree.root_person_id, tree.next_number), (admin.pk, marian.pk, 8))
        self.assertEqual(new.get_model("genealogy", "Person").objects.filter(tree=tree).count(), 2)
        self.assertEqual(new.get_model("genealogy", "Place").objects.get().tree_id, tree.pk)
        executor = MigrationExecutor(connection)                     # вернуть схему для других тестов
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


SMALL_GED = """0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Josef /Novák/
1 SEX M
1 BIRT
2 DATE 1900
2 PLAC Brno
0 @I2@ INDI
1 NAME Marie /Nováková/
1 SEX F
0 @I3@ INDI
1 NAME Jan /Novák/
1 SEX M
1 FAMC @F1@
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 CHIL @I3@
0 TRLR
"""


class StartTest(SmallTreeMixin, TestCase):
    """Первый вход: пустое древо — «Загрузить GEDCOM» или «Начать с нуля»."""

    def ged(self, text=SMALL_GED, name="drevo.ged", encoding="utf-8"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, text.encode(encoding))

    def test_window_only_for_empty_tree(self):
        self.assertContains(self.client.get("/"), 'id="start"')
        self.make_tree()
        self.assertNotContains(self.client.get("/"), 'id="start"')

    def test_start_with_own_card(self):
        r = self.client.post("/start/self/", {"given_name": "Marian", "birth_surname": "Hanus", "sex": "M",
                                              "birth_date": "6.1.2007", "birth_place": "Praha"})
        self.assertEqual(r.json(), {"redirect": "/#P0001"})
        self.tree.refresh_from_db()
        me = self.tree.root_person
        self.assertEqual((me.code, me.given_name, me.is_living), ("P0001", "Marian", True))
        self.assertEqual(me.events.get(kind="BIRT").date, "6 JAN 2007")
        self.assertEqual(self.client.post("/start/self/", {}).status_code, 409)     # второй раз — нельзя

    def test_card_without_any_data(self):
        self.assertEqual(self.client.post("/start/self/", {}).status_code, 200)
        self.assertEqual(self.tree.people.get().code, "P0001")

    def test_new_start_after_tree_was_emptied(self):
        self.person(given_name="Старый")
        self.person()
        Place.objects.create(tree=self.tree, name="Старое место")
        Person.objects.filter(tree=self.tree).delete()
        self.assertEqual(self.client.post("/start/self/", {"given_name": "Я"}).status_code, 200)
        self.assertEqual(self.tree.people.get().code, "P0001")                    # номера — заново
        self.assertFalse(Place.objects.filter(tree=self.tree, name="Старое место").exists())

    def test_gedcom_preview_saves_nothing(self):
        r = self.client.post("/start/gedcom/", {"action": "preview", "file": self.ged()})
        data = r.json()
        self.assertEqual([p["gid"] for p in data["people"]], ["@I1@", "@I2@", "@I3@"])
        self.assertEqual(data["people"][1]["name"], "Marie Nováková")
        self.assertEqual(data["families"], 1)
        self.assertFalse(self.tree.people.exists())

    def test_gedcom_import_chosen_person_becomes_p0001(self):
        r = self.client.post("/start/gedcom/", {"action": "import", "root": "@I3@", "file": self.ged()})
        self.assertEqual(r.json(), {"redirect": "/#P0001"})
        self.tree.refresh_from_db()
        me = self.tree.root_person
        self.assertEqual((me.code, me.given_name), ("P0001", "Jan"))
        self.assertEqual(self.tree.people.count(), 3)
        self.assertEqual({p.given_name for p in me.parent_family.partners}, {"Josef", "Marie"})
        self.assertEqual(self.client.get("/api/tree/").json()["root"], str(me.pk))
        r = self.client.post("/start/gedcom/", {"action": "import", "file": self.ged()})
        self.assertEqual(r.status_code, 409)                                        # уже не пустое

    def test_bad_files(self):
        def error(data):
            r = self.client.post("/start/gedcom/", data)
            self.assertEqual(r.status_code, 400)
            return r.json()["error"]
        self.assertIn("Выберите файл", error({"action": "preview"}))
        self.assertIn("не похоже на GEDCOM", error({"action": "preview", "file": self.ged("просто текст")}))
        self.assertIn("не найден", error({"action": "import", "root": "@I9@", "file": self.ged()}))
        self.assertFalse(self.tree.people.exists())

    def test_not_utf8_file_is_read_with_warning(self):
        data = self.client.post("/start/gedcom/", {"action": "preview",
                                                   "file": self.ged(encoding="cp1250")}).json()
        self.assertEqual(len(data["people"]), 3)
        self.assertIn("UTF-8", data["notes"][0])


class AccountTest(SmallTreeMixin, TestCase):
    """Страница «Аккаунт»: логин, пароль, удаление древа и учётной записи."""
    PASSWORD = "Древо-пароль-1"

    def setUp(self):
        import shutil
        import tempfile
        from django.test import override_settings
        super().setUp()
        self.make_tree()
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)
        self.media = Path(media)

    def post(self, action, **data):
        return self.client.post("/account/", {"action": action, **data})

    def add_material(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        source = Source.objects.create(tree=self.tree, category="memory", title="Свадьба")
        sf = SourceFile.objects.create(source=source, file=SimpleUploadedFile("foto.jpg", b"jpeg"))
        path = self.media / sf.file.name
        self.assertTrue(path.exists())
        return path

    def test_page_and_header_links(self):
        r = self.client.get("/account/")
        ids = __import__("re").findall(r'id="([^"]+)"', r.content.decode())
        self.assertEqual(len(ids), len(set(ids)), ids)                        # id не повторяются
        self.assertContains(r, "Вы вошли как <strong>owner</strong>")
        self.assertContains(r, "В древе 7 человек.")
        self.assertContains(r, 'action="/logout/"')
        for page in ("/", f"/people/{self.marian.code}/"):
            html = self.client.get(page)
            self.assertContains(html, 'class="avatar" href="/account/"')            # значок профиля
            self.assertNotContains(html, 'action="/logout/"')                      # «Выйти» — только в аккаунте

    def test_change_username_needs_password(self):
        r = self.post("username", username="novy", password="не тот")
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "Неверный пароль", status_code=400)
        self.assertContains(r, "Вы вошли как <strong>owner</strong>", status_code=400)
        r = self.post("username", username="owner", password=self.PASSWORD)
        self.assertContains(r, "нынешний логин", status_code=400)
        User.objects.create_user("zanyato")
        self.assertEqual(self.post("username", username="zanyato", password=self.PASSWORD).status_code, 400)

        r = self.post("username", username="novy", password=self.PASSWORD)
        self.assertRedirects(r, "/account/#login", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "novy")
        self.assertContains(self.client.get("/account/"), "Логин изменён")
        self.assertEqual(self.client.get("/api/tree/").status_code, 200)       # древо осталось своим

    def test_change_password_keeps_session(self):
        r = self.post("password", old_password="не тот", new_password1="Новый-пароль-77",
                      new_password2="Новый-пароль-77")
        self.assertEqual(r.status_code, 400)
        r = self.post("password", old_password=self.PASSWORD, new_password1="Новый-пароль-77",
                      new_password2="Новый-пароль-77")
        self.assertRedirects(r, "/account/#password", fetch_redirect_response=False)
        self.assertContains(self.client.get("/account/"), "Пароль изменён")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Новый-пароль-77"))
        self.assertEqual(self.client.get("/account/").status_code, 200)        # не выкинуло

    def test_clear_tree_needs_password_and_phrase(self):
        file = self.add_material()
        for data in ({"password": self.PASSWORD, "confirm": "удалить"},
                     {"password": "не тот", "confirm": "удалить древо"},
                     {"password": self.PASSWORD}):
            r = self.post("clear", **data)
            self.assertEqual(r.status_code, 400)
            self.assertContains(r, "<details class=\"danger\" id=\"danger\" open>", status_code=400)
        self.assertEqual(self.tree.people.count(), 7)

        with self.captureOnCommitCallbacks(execute=True):
            r = self.post("clear", password=self.PASSWORD, confirm="  Удалить   ДРЕВО ")
        self.assertRedirects(r, "/", fetch_redirect_response=False)
        self.tree.refresh_from_db()
        self.assertFalse(self.tree.people.exists())
        self.assertFalse(Source.objects.filter(tree=self.tree).exists())
        self.assertFalse(file.exists())                                       # файл удалён с диска
        self.assertEqual((self.tree.root_person, self.tree.next_number), (None, 1))
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())        # учётка осталась
        self.assertContains(self.client.get("/"), 'id="start"')               # окно первого входа

    def test_delete_account_with_tree(self):
        file = self.add_material()
        other = User.objects.create_user("drugoy")
        other_tree = FamilyTree.objects.create(owner=other)
        Person.objects.create(tree=other_tree, given_name="Чужой")
        r = self.post("delete", password=self.PASSWORD, confirm="OWNER")     # логин — точно
        self.assertContains(r, "Нужно вписать «owner»", status_code=400)

        with self.captureOnCommitCallbacks(execute=True):
            r = self.post("delete", password=self.PASSWORD, confirm="owner")
        self.assertContains(r, "Учётная запись удалена")
        self.assertFalse(User.objects.filter(username="owner").exists())
        self.assertFalse(FamilyTree.objects.filter(pk=self.tree.pk).exists())
        self.assertFalse(Person.objects.filter(tree_id=self.tree.pk).exists())
        self.assertFalse(file.exists())
        self.assertEqual(other_tree.people.count(), 1)                        # чужое не тронуто
        self.assertRedirects(self.client.get("/"), "/login/?next=/")          # вышли

    def test_last_admin_cannot_delete_self(self):
        self.user.is_superuser = True
        self.user.save()
        self.assertContains(self.client.get("/account/"), "единственный администратор")
        r = self.post("delete", password=self.PASSWORD, confirm="owner")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        User.objects.create_superuser("admin2", "a@a.cz", "pw")
        r = self.post("delete", password=self.PASSWORD, confirm="owner")
        self.assertContains(r, "Учётная запись удалена")


class StaticVersionTest(SmallTreeMixin, TestCase):
    """К адресам CSS и JS добавляется версия: после правки файла браузер берёт новый."""

    def test_pages_link_versioned_files(self):
        import hashlib
        root = Path(__file__).resolve().parent.parent / "static" / "genealogy"
        html = self.client.get("/").content.decode()
        for name in ("tree.css", "tree.js"):
            version = hashlib.md5((root / name).read_bytes()).hexdigest()[:10]
            self.assertIn(f"/static/genealogy/{name}?v={version}", html)
        self.client.logout()
        self.assertContains(self.client.get("/login/"), "/static/genealogy/auth.css?v=")

    def test_version_changes_with_content(self):
        import os
        import tempfile
        from .static_version import file_version
        fd, path = tempfile.mkstemp(suffix=".css")
        os.close(fd)
        self.addCleanup(os.remove, path)
        Path(path).write_text("a { color: red; }")
        first = file_version(path)
        self.assertEqual(file_version(path), first)
        Path(path).write_text("a { color: blue; }")
        os.utime(path, (1, 1))                      # время изменения точно другое
        self.assertNotEqual(file_version(path), first)


class LanguageTest(SmallTreeMixin, TestCase):
    """Язык интерфейса: русский, английский, чешский."""

    def test_before_login_language_follows_browser(self):
        self.client.logout()
        cases = {"cs-CZ,cs;q=0.9": "Přihlášení", "en-US,en;q=0.8": "Sign in", "ru-RU": "Вход",
                 "de-DE,de;q=0.9": "Sign in"}                  # незнакомый язык браузера — английский
        for header, text in cases.items():
            r = Client(headers={"Accept-Language": header}).get("/login/")
            self.assertContains(r, f"<h1>{text}</h1>", msg_prefix=header)
        r = Client().get("/login/")                           # без заголовка — русский
        self.assertContains(r, "<h1>Вход</h1>")

    def test_switcher_before_login(self):
        self.client.logout()
        client = Client(headers={"Accept-Language": "ru"})
        r = client.get("/lang/cs/?next=/login/")
        self.assertRedirects(r, "/login/", fetch_redirect_response=False)
        self.assertContains(client.get("/login/"), "<h1>Přihlášení</h1>")
        self.assertContains(client.get("/login/"), 'href="/lang/en/?next=/login/"')
        self.assertContains(client.get("/login/"), 'hreflang="en">English</a>')   # названия — на самих себе
        r = client.get("/lang/en/?next=https://example.com/")      # чужой адрес — на вход
        self.assertRedirects(r, "/login/", fetch_redirect_response=False)
        client.get("/lang/xx/?next=/login/")                       # неизвестный язык — без изменений
        self.assertContains(client.get("/login/"), "<h1>Sign in</h1>")

    def test_registration_language_choice(self):
        self.client.logout()
        invitation = Invitation.objects.create()
        url = f"/invite/{invitation.code}/"
        page = Client(headers={"Accept-Language": "cs"}).get(url)
        self.assertContains(page, '<option value="cs" selected>')       # по браузеру
        self.assertContains(page, "Registrace")
        r = self.client.post(url, {"language": "en", "username": "jana", "password1": "Velka-rodina-1890",
                                   "password2": "Velka-rodina-1890"})
        self.assertRedirects(r, "/", fetch_redirect_response=False)
        self.assertEqual(User.objects.get(username="jana").profile.language, "en")
        self.assertContains(self.client.get("/account/"), "<h1>Account</h1>")
        self.assertEqual(self.client.cookies["django_language"].value, "en")

    def test_change_language_in_account(self):
        self.make_tree()
        self.assertContains(self.client.get("/account/"), "<h1>Аккаунт</h1>")   # по умолчанию — русский
        r = self.client.post("/account/", {"action": "language", "language": "cs"})
        self.assertRedirects(r, "/account/#language", fetch_redirect_response=False)
        page = self.client.get("/account/")
        self.assertContains(page, "<h1>Účet</h1>")
        self.assertContains(page, "Jazyk rozhraní byl změněn.")
        self.assertContains(page, 'lang="cs"')
        self.assertContains(page, "V rodokmenu je 7 osob.")                    # мн. число по-чешски
        self.assertEqual(self.client.cookies["django_language"].value, "cs")
        # фраза подтверждения — на языке интерфейса
        r = self.client.post("/account/", {"action": "clear", "password": "Древо-пароль-1",
                                           "confirm": "smazat rodokmen"})
        self.assertRedirects(r, "/", fetch_redirect_response=False)

    def test_russian_plural(self):
        from django.utils import translation
        from django.utils.translation import ngettext
        with translation.override("ru"):
            forms = [ngettext("В древе %(n)s человек.", "В древе %(n)s человек.", n) % {"n": n} for n in (1, 3, 5)]
        self.assertEqual(forms, ["В древе 1 человек.", "В древе 3 человека.", "В древе 5 человек."])

    def test_every_string_is_translated(self):
        """Строки для перевода из кода — все с переводом в en и cs (и мн. число в ru).

        Упал — запустите «python manage.py translations» и впишите переводы в locale/*/LC_MESSAGES/*.po.
        """
        from .i18n import LANGS, extract, needs_translation, po_path, read_po
        problems = []
        for domain, messages in extract().items():
            for lang in LANGS:
                _header, done = read_po(po_path(lang, domain))
                for key, msg in messages.items():
                    if not needs_translation(lang, msg):
                        continue
                    have = done.get(key)
                    if have is None or not have.msgstr or not all(have.msgstr):
                        problems.append(f"{lang}/{domain}: {msg.msgid!r} ({msg.refs[0]})")
        self.assertEqual(problems, [], "\n" + "\n".join(problems[:30]))

    def test_mo_compiler_matches_gettext(self):
        import gettext
        import tempfile
        from .i18n import compile_mo
        po = Path(tempfile.mkdtemp()) / "cs" / "LC_MESSAGES" / "django.po"
        po.parent.mkdir(parents=True)
        self.addCleanup(__import__("shutil").rmtree, po.parent.parent.parent, ignore_errors=True)
        po.write_text('''msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"
"Plural-Forms: nplurals=3; plural=(n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2;\\n"

msgid "Дом"
msgstr "Dům"

msgid "Строка с \\"кавычками\\""
msgstr "Řádek s \\"uvozovkami\\""

msgid "%(n)s дом"
msgid_plural "%(n)s домов"
msgstr[0] "%(n)s dům"
msgstr[1] "%(n)s domy"
msgstr[2] "%(n)s domů"

msgid "Без перевода"
msgstr ""
''', encoding="utf-8")
        import io
        catalog = gettext.GNUTranslations(io.BytesIO(compile_mo(po)))
        self.assertEqual(catalog.gettext("Дом"), "Dům")
        self.assertEqual(catalog.gettext('Строка с "кавычками"'), 'Řádek s "uvozovkami"')
        self.assertEqual([catalog.ngettext("%(n)s дом", "%(n)s домов", n) for n in (1, 3, 7)],
                         ["%(n)s dům", "%(n)s domy", "%(n)s domů"])
        self.assertEqual(catalog.gettext("Без перевода"), "Без перевода")

    def test_main_page_and_js_catalog_follow_user_language(self):
        self.make_tree()
        UserProfile = __import__("genealogy.models", fromlist=["UserProfile"]).UserProfile
        UserProfile.objects.update_or_create(user=self.user, defaults={"language": "cs"})
        page = self.client.get("/")
        self.assertContains(page, '<html lang="cs">')
        self.assertContains(page, "Celý rodokmen")                         # «Всё древо»
        self.assertContains(page, '<script src="/jsi18n/?l=cs">')
        catalog = self.client.get("/jsi18n/?l=cs").content.decode()
        self.assertIn("Sourozenci", catalog)                               # «Братья и сёстры» из tree.js
        self.assertIn("generac", catalog)                                  # мн. число
        self.assertIn("no-cache", self.client.get("/jsi18n/")["Cache-Control"])
        panel = self.client.get(f"/api/people/{self.marian.pk}/").json()
        self.assertEqual(panel["sex_label"], "Muž")
        self.assertEqual(panel["key"][0]["label"], "Narození")
        self.assertEqual(panel["key"][0]["date"], "6. ledna 2007")                # месяц словом — по-чешски
        self.assertIn("kolem 1850", catalog)                                      # подсказка формата дат в «+»
        self.client.post("/account/", {"action": "language", "language": "en"})
        self.assertContains(self.client.get("/"), "Whole tree")

    def test_person_page_in_czech(self):
        self.make_tree()
        from .models import UserProfile
        UserProfile.objects.update_or_create(user=self.user, defaults={"language": "cs"})
        page = self.client.get(f"/people/{self.libor.code}/")
        self.assertContains(page, '<html lang="cs">')
        self.assertContains(page, "O osobě")                                   # вкладка «О человеке»
        self.assertContains(page, "Rodné příjmení")                            # подпись поля из модели
        self.assertContains(page, "Narození syna")                             # хронология
        self.assertContains(page, "6. ledna 2007")                             # дата рождения сына
        # сообщение ядра (почему нельзя удалить) — тоже по-чешски
        self.assertContains(page, "osoba má rodiče i děti")
        r = self.client.post(f"/people/{self.marian.code}/", {"action": "delete", "confirm_code": "P9999"},
                             headers={"X-Requested-With": "fetch"})
        self.assertIn("Číslo nesouhlasí", r.json()["message"])
