"""Тесты ядра. Запуск из корня проекта:  python -m unittest -v"""
import unittest
from pathlib import Path

from tree_engine.gedcom import load, parse
from tree_engine.generations import assign_generations
from tree_engine.layout import CARD_W, compute_layout, count_crossings
from tree_engine.model import Family, FuzzyDate, Person, Tree, deletion_blockers, lifespan
from tree_engine.render_svg import rounded_path

GED = Path(__file__).parent / "rootsmagic_tree.ged"   # личные данные — не в git!
needs_ged = unittest.skipUnless(GED.exists(), "нет tests/rootsmagic_tree.ged")


def build(people: dict, families: list) -> Tree:
    """Маленькое древо для тестов.
    people: {id: (имя, пол, год)}; families: [(id, [партнёры], [дети])]"""
    t = Tree()
    for pid, (name, sex, year) in people.items():
        p = Person(pid, given=name, sex=sex)
        if year:
            from tree_engine.model import Event
            p.events.append(Event("BIRT", FuzzyDate(str(year))))
        t.people[pid] = p
    for fid, partners, children in families:
        t.families[fid] = Family(fid, list(partners), list(children))
        for p in partners:
            t.people[p].families.append(fid)
        for c in children:
            t.people[c].parent_family = fid
    return t


# Отец Libor: 1-й брак (сын Ondřej, 1986), 2-й брак с Юлией (сын Marian, 2007).
# У Юлии записан только отец Евгений, без его предков.
HANUS = build(
    {"praded": ("Прадед", "M", 1900), "ded": ("Дед", "M", 1932), "libor": ("Libor", "M", 1962),
     "wife1": ("1-я жена", "F", 1964), "julia": ("Юлия", "F", 1970), "evg": ("Евгений", "M", 1947),
     "ondrej": ("Ondřej", "M", 1986), "marian": ("Marian", "M", 2007), "uncle": ("Дядя", "M", 1959)},
    [("f_old", ["praded"], ["ded"]), ("f_ded", ["ded"], ["uncle", "libor"]),
     ("f1", ["libor", "wife1"], ["ondrej"]), ("f2", ["libor", "julia"], ["marian"]),
     ("f_evg", ["evg"], ["julia"])],
)


class FuzzyDateTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(FuzzyDate("6 JAN 2007").sort_key, (2007, 1, 6))
        self.assertEqual(FuzzyDate("1745").year, 1745)
        self.assertEqual(FuzzyDate("ABT 1850").short(), "~1850")
        self.assertEqual(FuzzyDate("BEF 1790").short(), "<1790")
        self.assertEqual(FuzzyDate("BET 1850 AND 1860").year, 1850)

    def test_short_inexact_years(self):
        cases = {"BET 1850 AND 1852": "1850-52", "BET 1799 AND 1801": "1799-1801",
                 "BET 1 JAN 1850 AND 1852": "1850-52", "BEF 1850": "<1850", "AFT 1850": ">1850",
                 "1850/51": "1850/51", "6 JAN 2007": "2007"}
        for raw, expected in cases.items():
            self.assertEqual(FuzzyDate(raw).short(), expected, raw)

    def test_lifespan(self):
        F = FuzzyDate
        self.assertEqual(lifespan(F("1849"), False, None, False), "1849–?")
        self.assertEqual(lifespan(F("2007"), False, None, True), "2007–")
        self.assertEqual(lifespan(F("1804/05"), True, F("1878"), False), "1804/05–1878")
        self.assertEqual(lifespan(F("AFT 1800"), True, F("1878"), False), ">1800–1878")
        self.assertEqual(lifespan(F("BEF 1810"), True, F("1878"), False), "<1810–1878")
        self.assertEqual(lifespan(F("1804"), True, F("BEF 1880"), False), "1804–<1880")
        self.assertEqual(lifespan(F("1804"), True, F("AFT 1870"), False), "1804–>1870")
        self.assertEqual(lifespan(None, True, None, False), "?–?")       # умер, даты нет
        self.assertEqual(lifespan(None, False, None, False), "")         # ничего не известно


@needs_ged
class GedcomTest(unittest.TestCase):
    def setUp(self):
        self.tree = load(GED)

    def test_counts_and_integrity(self):
        self.assertEqual(len(self.tree.people), 108)
        self.assertEqual(len(self.tree.families), 47)
        self.assertEqual(self.tree.validate(), [])

    def test_patronymic_and_multiple_marriages(self):
        julia = self.tree.people["@I3@"]
        self.assertEqual((julia.given, julia.patronymic, julia.surname), ("Юлия", "Евгеньевна", "Секо"))
        self.assertEqual(len(self.tree.people["@I2@"].families), 2)   # Libor: два брака

    def test_person_without_any_data(self):
        t = parse("0 @I1@ INDI\n0 @F1@ FAM\n1 CHIL @I1@\n0 TRLR")
        self.assertEqual(t.people["@I1@"].years(), "")
        self.assertEqual(t.people["@I1@"].display_given, "?")


class GenerationsTest(unittest.TestCase):
    def test_half_brother_same_generation_regardless_of_age(self):
        gen, warnings = assign_generations(HANUS, "marian")
        self.assertEqual(gen["marian"], 1)
        self.assertEqual(gen["ondrej"], 1)          # родился в 1986, но поколение то же
        self.assertEqual(gen["libor"], 2)
        self.assertEqual(gen["praded"], 4)
        self.assertEqual(warnings, [])

    def test_married_in_spouse_parent_is_one_level_above_her(self):
        # Именно здесь ломался старый код: Евгений улетал на уровень прадеда.
        gen, _ = assign_generations(HANUS, "marian")
        self.assertEqual(gen["julia"], 2)
        self.assertEqual(gen["evg"], 3)

    def test_youngest_row_is_generation_one(self):
        # У опорного человека появился племянник: нумерация начинается с племянника, без 0.
        t = build({"me": ("Я", "M", None), "bro": ("Брат", "M", None), "dad": ("Отец", "M", None),
                   "kid": ("Племянница", "F", None)},
                  [("fd", ["dad"], ["me", "bro"]), ("fb", ["bro"], ["kid"])])
        gen, _ = assign_generations(t, "me")
        self.assertEqual((gen["kid"], gen["me"], gen["bro"], gen["dad"]), (1, 2, 2, 3))
        self.assertEqual(min(gen.values()), 1)

    @needs_ged
    def test_parents_always_above_children_on_real_tree(self):
        tree = load(GED)
        gen, _ = assign_generations(tree, "@I1@")
        for fam in tree.families.values():
            for c in fam.children:
                for p in fam.partners:
                    self.assertGreater(gen[p], gen[c])


class DeletionTest(unittest.TestCase):
    def test_person_in_middle_of_line_cannot_be_deleted(self):
        self.assertTrue(deletion_blockers(HANUS, "libor"))     # есть и отец, и дети

    def test_top_ancestor_with_children_can_be_deleted(self):
        t = build({"x": ("Дед", "M", None), "a": ("Сын", "M", None), "b": ("Дочь", "F", None)},
                  [("f", ["x"], ["a", "b"])])
        self.assertEqual(deletion_blockers(t, "x"), [])        # выше него никого нет

    def test_childless_one_of_several_children_can_be_deleted(self):
        self.assertEqual(deletion_blockers(HANUS, "uncle"), [])

    def test_deletion_that_creates_island_is_blocked(self):
        # Бездетная Юлия: её отец Евгений остался бы оторванным островком.
        t = build({"a": ("A", "M", None), "b": ("B", "F", None), "bf": ("Отец B", "M", None)},
                  [("f", ["a", "b"], []), ("fb", ["bf"], ["b"])])
        self.assertIn("островок", " ".join(deletion_blockers(t, "b")))

    def test_only_child_whose_parents_have_no_other_link(self):
        t = build({"p": ("Отец", "M", None), "m": ("Мать", "F", None), "c": ("Сын", "M", None),
                   "x": ("Дед", "M", None)},
                  [("fx", ["x"], ["p"]), ("f", ["p", "m"], ["c"])])
        self.assertEqual(deletion_blockers(t, "c"), [])   # родители связаны браком — ок
        self.assertTrue(deletion_blockers(t, "p"))         # есть и отец, и ребёнок


class LayoutTest(unittest.TestCase):
    def check_no_overlap(self, tree, layout):
        rows = {}
        for b in layout.boxes.values():
            rows.setdefault(b.y, []).append(b.x)
        for xs in rows.values():
            xs.sort()
            for a, b in zip(xs, xs[1:]):
                self.assertGreaterEqual(b - a, CARD_W)

    def test_lines_start_from_union_point(self):
        # Один ствол от точки брака, от шины — ветки к детям; каждая ветка начинается на стволе.
        t = build({"f": ("Отец", "M", None), "m": ("Мать", "F", None),
                   "a": ("A", "M", None), "b": ("B", "F", None), "c": ("C", "M", None)},
                  [("fam", ["f", "m"], ["a", "b", "c"])])
        lay = compute_layout(t, "a")
        u = lay.unions["fam"]
        descents = [ln.points for ln in lay.lines if ln.kind == "descent"]
        trunks = [p for p in descents if p[0] == (u.x, u.y)]
        self.assertEqual(len(trunks), 1)
        bus_y = trunks[0][-1][1]
        self.assertEqual(len(descents), 4)
        for p in descents:
            if p is not trunks[0]:
                self.assertEqual(p[0], (u.x, bus_y))

    def test_only_child_almost_under_union_gets_straight_line(self):
        t = build({"p": ("Отец", "M", None), "c": ("Сын", "M", None)}, [("fam", ["p"], ["c"])])
        lay = compute_layout(t, "c")
        (path,) = [ln.points for ln in lay.lines if ln.kind == "descent"]
        self.assertTrue(abs(lay.boxes["c"].x - lay.unions["fam"].x) <= 24)
        self.assertEqual({x for x, _ in path}, {lay.unions["fam"].x})   # вертикаль без ступеньки

    def test_lonely_partner_without_children_draws_nothing(self):
        t = build({"j": ("Josef", "M", None), "r": ("Renata", "F", None), "t": ("Taťána", "F", None)},
                  [("old", ["j"], []), ("fam", ["j", "t"], ["r"])])
        lay = compute_layout(t, "r")
        self.assertNotIn("old", lay.unions)
        self.assertFalse([ln for ln in lay.lines if ln.fid == "old"])

    def test_rounded_path_drops_points_on_straight_line(self):
        self.assertEqual(rounded_path([(5, 0), (5, 10), (5, 10), (5, 40)]), "M 5.0 0.0 L 5.0 40.0")

    def test_second_marriage_layout(self):
        layout = compute_layout(HANUS, "marian")
        self.check_no_overlap(HANUS, layout)
        b = layout.boxes
        self.assertLess(b["wife1"].x, b["libor"].x)    # Libor между двумя жёнами
        self.assertLess(b["libor"].x, b["julia"].x)
        self.assertLess(b["ondrej"].x, b["marian"].x)  # дети под своими союзами
        self.assertEqual(b["ondrej"].y, b["marian"].y)
        self.assertEqual(count_crossings(HANUS, layout), 0)

    @needs_ged
    def test_real_tree(self):
        tree = load(GED)
        layout = compute_layout(tree, "@I1@")
        self.assertEqual(len(layout.boxes), 108)
        self.assertEqual(len(layout.rows), 9)
        self.check_no_overlap(tree, layout)
        self.assertLessEqual(count_crossings(tree, layout), 5)   # защита от регрессии


if __name__ == "__main__":
    unittest.main()


class RoundedPathTest(unittest.TestCase):
    def test_corner_is_rounded_and_short_segments_shrink_radius(self):
        d = rounded_path([(0, 0), (0, 10), (100, 10)], radius=12)
        self.assertIn("Q 0.0 10.0", d)                 # скругление вокруг угла
        self.assertIn("L 0.0 5.0", d)                  # радиус урезан до половины отрезка
        self.assertEqual(rounded_path([(0, 0), (0, 50)]), "M 0.0 0.0 L 0.0 50.0")


class UserDateInputTest(unittest.TestCase):
    def test_normalize(self):
        from tree_engine.model import normalize_date
        cases = {"10.08.1962": "10 AUG 1962", "8.1962": "AUG 1962", "1962": "1962",
                 "около 1850": "ABT 1850", "до 1790": "BEF 1790", "после 1900": "AFT 1900",
                 "1850-1860": "BET 1850 AND 1860", "6 jan 2007": "6 JAN 2007", "весна 1945": "весна 1945",
                 "1850-52": "BET 1850 AND 1852", "1850/51": "1850/51", "1850/1851": "1850/51"}
        for given, expected in cases.items():
            self.assertEqual(normalize_date(given), expected, given)

    def test_display(self):
        self.assertEqual(FuzzyDate("10 AUG 1962").display_ru(), "10 августа 1962")
        self.assertEqual(FuzzyDate("BET 1850 AND 1860").display_ru(), "между 1850 и 1860")

    def test_round_trip_to_user_format(self):
        from tree_engine.model import normalize_date, to_user_date
        for text in ["10.08.1962", "08.1962", "1962", "около 1850", "до 1790", "между 1850 и 1860", "весна 1945",
                     "1850/51"]:
            self.assertEqual(to_user_date(normalize_date(text)), text)
