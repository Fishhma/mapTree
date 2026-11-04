"""Тесты Django-части.  Запуск: python manage.py test"""
import unittest
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from .models import Event, Family, Person, Place, Source, SourceFile, TreeSettings

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
        josef, renata = Person.objects.create(given_name="Josef"), Person.objects.create(given_name="Renata")
        fam = family(josef, None, [renata])
        tatana = self.new_person(self.add(josef, "spouse", family=fam.pk, given_name="Taťána", sex="F"))
        fam.refresh_from_db()
        self.assertEqual((fam.partner1, fam.partner2), (josef, tatana))
        self.assertEqual(josef.families.count(), 1)                # новой семьи не появилось
        tree = self.client.get("/api/tree/").json()
        self.assertEqual(sorted(tree["families"][str(fam.pk)]["partners"]), sorted([str(josef.pk), str(tatana.pk)]))
        self.assertEqual(tree["families"][str(fam.pk)]["children"], [str(renata.pk)])

    def test_spouse_fills_first_slot_if_person_is_second(self):
        mother, kid = Person.objects.create(given_name="Мать"), Person.objects.create(given_name="Ребёнок")
        fam = family(None, mother, [kid])
        father = self.new_person(self.add(mother, "spouse", family=fam.pk))
        fam.refresh_from_db()
        self.assertEqual((fam.partner1, fam.partner2), (father, mother))

    def test_spouse_as_new_marriage_when_family_not_chosen(self):
        josef, renata = Person.objects.create(given_name="Josef"), Person.objects.create(given_name="Renata")
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
        from django.test import Client
        r = Client(enforce_csrf_checks=True).post(f"/api/people/{self.marian.pk}/add/", {"relation": "child"},
                                                 content_type="application/json")
        self.assertEqual(r.status_code, 403)


class PersonPageTest(SmallTreeMixin, TestCase):
    """Страница /people/P0001/: вкладки, правка и удаление только здесь."""

    def setUp(self):
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
