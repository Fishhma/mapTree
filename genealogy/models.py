"""Модели базы данных.

Ключевая идея та же, что в ядре: ребёнок принадлежит СЕМЬЕ (союзу двух людей),
а не отдельному родителю. Повторный брак — это ещё одна семья.
Ни одно поле человека не обязательно.
"""
from django.core.exceptions import ValidationError
from django.db import models

from tree_engine.model import FuzzyDate, normalize_date


class Person(models.Model):
    class Sex(models.TextChoices):
        MALE = "M", "Мужской"
        FEMALE = "F", "Женский"
        UNKNOWN = "U", "Неизвестен"

    code = models.CharField("номер", max_length=12, unique=True, blank=True, editable=False)
    given_name = models.CharField("имя", max_length=120, blank=True)
    patronymic = models.CharField("отчество", max_length=120, blank=True)
    birth_surname = models.CharField(
        "фамилия при рождении", max_length=120, blank=True,
        help_text="Для женщин — девичья. Смена фамилии хранится в вариантах имени.")
    sex = models.CharField("пол", max_length=1, choices=Sex.choices, default=Sex.UNKNOWN)
    is_living = models.BooleanField(
        "жив(а)", default=False,
        help_text="Без даты смерти в древе: у живых «2007–», у остальных «1849–?».")
    parent_family = models.ForeignKey(
        "Family", verbose_name="семья родителей", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="children")
    child_order = models.PositiveSmallIntegerField(
        "порядок среди детей", null=True, blank=True,
        help_text="Нужен, только если дат рождения нет, а порядок известен.")
    notes = models.TextField("краткое жизнеописание", blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "человек"
        verbose_name_plural = "люди"
        ordering = ["code"]

    def __str__(self):
        name = " ".join(x for x in (self.given_name, self.patronymic, self.birth_surname) if x)
        return f"{name or '?'} ({self.code})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.code:      # собственная нумерация: P0001, P0002, …
            self.code = f"P{self.pk:04d}"
            super().save(update_fields=["code"])

    @property
    def full_name(self) -> str:
        return " ".join(x for x in (self.given_name, self.patronymic, self.birth_surname) if x) or "?"

    @property
    def families(self):
        return Family.objects.filter(models.Q(partner1=self) | models.Q(partner2=self))

    def deletion_blockers(self) -> list[str]:
        from tree_engine.model import deletion_blockers
        from .bridge import build_tree
        return deletion_blockers(build_tree(), str(self.pk))


class Family(models.Model):
    """Союз (брак или пара). Партнёров 0–2: неизвестный родитель — пустое поле."""
    partner1 = models.ForeignKey(Person, verbose_name="партнёр 1", null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    partner2 = models.ForeignKey(Person, verbose_name="партнёр 2", null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    notes = models.TextField("заметки", blank=True)

    class Meta:
        verbose_name = "семья"
        verbose_name_plural = "семьи"

    def __str__(self):
        names = [str(p) for p in (self.partner1, self.partner2) if p]
        return " + ".join(names) or f"Семья №{self.pk} (родители неизвестны)"

    def clean(self):
        if self.partner1_id and self.partner1_id == self.partner2_id:
            raise ValidationError("Партнёры должны быть разными людьми.")

    @property
    def partners(self):
        return [p for p in (self.partner1, self.partner2) if p]


class Place(models.Model):
    name = models.CharField("название", max_length=255, unique=True,
                            help_text="Например: Boskovice, Blansko, Чехия")
    latitude = models.FloatField("широта", null=True, blank=True)
    longitude = models.FloatField("долгота", null=True, blank=True)
    notes = models.TextField("заметки", blank=True)

    class Meta:
        verbose_name = "место"
        verbose_name_plural = "места"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Event(models.Model):
    """Событие или факт человека либо семьи."""
    class Kind(models.TextChoices):
        BIRTH = "BIRT", "Рождение"
        CHRISTENING = "CHR", "Крещение"
        DEATH = "DEAT", "Смерть"
        BURIAL = "BURI", "Погребение"
        MARRIAGE = "MARR", "Брак"
        DIVORCE = "DIV", "Развод"
        RESIDENCE = "RESI", "Место жительства"
        EDUCATION = "EDUC", "Образование"
        MILITARY = "MILI", "Военная служба"
        EMIGRATION = "EMIG", "Эмиграция"
        OCCUPATION = "OCCU", "Профессия"
        RELIGION = "RELI", "Вероисповедание"
        NATIONALITY = "NATI", "Национальность"
        OTHER = "EVEN", "Другое"

    KEY_KINDS = {"BIRT", "CHR", "DEAT", "BURI"}          # «ключевые сведения»
    FACT_KINDS = {"OCCU", "RELI", "NATI"}                # «факты» — без даты по смыслу

    person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.CASCADE,
                               related_name="events", verbose_name="человек")
    family = models.ForeignKey(Family, null=True, blank=True, on_delete=models.CASCADE,
                               related_name="events", verbose_name="семья")
    kind = models.CharField("тип", max_length=4, choices=Kind.choices)
    title = models.CharField("название (для «Другое»)", max_length=120, blank=True)
    date = models.CharField(
        "дата", max_length=60, blank=True,
        help_text="10.08.1962 · 1962 · около 1850 · до 1790 · после 1900 · 1850-1860")
    sort_key = models.IntegerField(default=99999999, editable=False)
    place = models.ForeignKey(Place, null=True, blank=True, on_delete=models.SET_NULL,
                              verbose_name="место")
    value = models.CharField("значение", max_length=255, blank=True,
                             help_text="Для фактов: например, «кузнец»")
    description = models.TextField("описание", blank=True)

    class Meta:
        verbose_name = "событие / факт"
        verbose_name_plural = "события и факты"
        ordering = ["sort_key", "id"]
        constraints = [models.CheckConstraint(
            condition=(models.Q(person__isnull=False, family__isnull=True)
                       | models.Q(person__isnull=True, family__isnull=False)),
            name="event_belongs_to_person_or_family")]

    def __str__(self):
        return " ".join(x for x in (self.get_kind_display(), self.date_display) if x)

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.date)
        self.sort_key = FuzzyDate(self.date).sort_int if self.date else 99999999
        super().save(*args, **kwargs)

    @property
    def date_display(self) -> str:
        return FuzzyDate(self.date).display_ru() if self.date else ""

    @property
    def label(self) -> str:
        return self.title if self.kind == self.Kind.OTHER and self.title else self.get_kind_display()


class PersonName(models.Model):
    """Варианты имени: в браке, после развода, транслитерация, при крещении…"""
    class Kind(models.TextChoices):
        MARRIED = "married", "В браке"
        CHANGED = "changed", "Смена фамилии"
        ALIAS = "alias", "Также известен как"
        TRANSLIT = "translit", "Другое написание / транслитерация"
        RELIGIOUS = "religious", "Имя при крещении"

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="names")
    kind = models.CharField("тип", max_length=12, choices=Kind.choices, default=Kind.ALIAS)
    given_name = models.CharField("имя", max_length=120, blank=True)
    patronymic = models.CharField("отчество", max_length=120, blank=True)
    surname = models.CharField("фамилия", max_length=120, blank=True)
    date = models.CharField("с какого времени", max_length=60, blank=True)
    note = models.CharField("примечание", max_length=255, blank=True)

    class Meta:
        verbose_name = "вариант имени"
        verbose_name_plural = "варианты имени"

    def __str__(self):
        return " ".join(x for x in (self.given_name, self.patronymic, self.surname) if x)

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.date)
        super().save(*args, **kwargs)


class Source(models.Model):
    """Материал: источник (документ) или воспоминание (фото, работа человека).

    Хранится один раз и привязывается к любому числу людей через Citation —
    например, одна семейная фотография у каждого, кто на ней есть.
    """
    class Category(models.TextChoices):
        SOURCE = "source", "Источник"
        MEMORY = "memory", "Воспоминание"

    class Kind(models.TextChoices):
        BIRTH = "birth", "Запись о рождении"
        BAPTISM = "baptism", "Запись о крещении"
        MARRIAGE = "marriage", "Запись о браке"
        DEATH = "death", "Запись о смерти"
        CENSUS = "census", "Перепись"
        PHOTO = "photo", "Фотография"
        LETTER = "letter", "Письмо / личный документ"
        OTHER = "other", "Другое"

    category = models.CharField("раздел", max_length=8, choices=Category.choices,
                                default=Category.SOURCE)
    title = models.CharField("название", max_length=255)
    kind = models.CharField("тип", max_length=12, choices=Kind.choices, default=Kind.OTHER)
    date = models.CharField("дата события", max_length=60, blank=True)
    created = models.DateTimeField("добавлен", auto_now_add=True, null=True)
    repository = models.CharField("где хранится", max_length=255, blank=True,
                                  help_text="Архив, книга, семейный альбом…")
    reference = models.CharField("шифр / ссылка", max_length=500, blank=True)
    notes = models.TextField("заметки / расшифровка", blank=True)

    class Meta:
        verbose_name = "источник"
        verbose_name_plural = "источники"
        ordering = ["title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.date)
        super().save(*args, **kwargs)

    @property
    def date_display(self) -> str:
        return FuzzyDate(self.date).display_ru() if self.date else ""

    @property
    def sort_key(self) -> int:
        return FuzzyDate(self.date).sort_int if self.date else 99999999


class SourceFile(models.Model):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="files")
    file = models.FileField("файл", upload_to="sources/%Y/")
    caption = models.CharField("подпись", max_length=255, blank=True)
    sha256 = models.CharField("отпечаток файла", max_length=64, blank=True, db_index=True, editable=False,
                              help_text="По нему узнаётся повторная загрузка того же файла.")

    class Meta:
        verbose_name = "файл"
        verbose_name_plural = "файлы (сканы, фото)"

    def __str__(self):
        return self.caption or self.file.name

    @property
    def is_image(self) -> bool:
        return self.file.name.lower().rsplit(".", 1)[-1] in {"jpg", "jpeg", "png", "gif", "webp", "tif", "tiff"}


class Citation(models.Model):
    """Связь «источник ↔ человек» (и, по желанию, конкретное событие)."""
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="citations",
                               verbose_name="источник")
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="citations",
                               verbose_name="человек")
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="citations", verbose_name="событие")
    detail = models.CharField("где именно", max_length=255, blank=True,
                              help_text="Страница, строка, кто на фото слева направо…")

    class Meta:
        verbose_name = "ссылка на источник"
        verbose_name_plural = "ссылки на источники"
        constraints = [models.UniqueConstraint(fields=["source", "person", "event"],
                                               name="unique_citation")]

    def __str__(self):
        return f"{self.source} → {self.person}"


class TreeSettings(models.Model):
    """Единственная запись: от кого считать поколения."""
    root_person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.SET_NULL,
                                    verbose_name="опорный человек (поколение 1)")

    class Meta:
        verbose_name = "настройки древа"
        verbose_name_plural = "настройки древа"

    def __str__(self):
        return "Настройки древа"

    @classmethod
    def get(cls) -> "TreeSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
