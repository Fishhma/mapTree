"""Модели базы данных.

Ключевая идея та же, что в ядре: ребёнок принадлежит СЕМЬЕ (союзу двух людей),
а не отдельному родителю. Повторный брак — это ещё одна семья.
Ни одно поле человека не обязательно.

У каждого пользователя своё древо (FamilyTree): люди, семьи, места и материалы
принадлежат древу, номера P0001, P0002, … считаются внутри древа.
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from tree_engine.model import FuzzyDate, normalize_date


class FamilyTree(models.Model):
    """Древо одного пользователя."""
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
                                 related_name="family_tree", verbose_name=_("владелец"))
    root_person = models.ForeignKey("Person", null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+", verbose_name=_("опорный человек (поколение 1)"))
    next_number = models.PositiveIntegerField(_("следующий номер"), default=1,
                                              help_text=_("Номер, который получит следующий новый человек."))
    created = models.DateTimeField(_("создано"), auto_now_add=True)

    class Meta:
        verbose_name = _("древо")
        verbose_name_plural = _("древа")

    def __str__(self):
        return (_("Древо %(owner)s") % {"owner": self.owner} if self.owner
                else _("Древо №%(pk)s (без владельца)") % {"pk": self.pk})

    @classmethod
    def of(cls, user) -> "FamilyTree":
        """Древо пользователя (создаётся, если его ещё нет)."""
        tree, _ = cls.objects.get_or_create(owner=user)
        return tree

    def take_number(self) -> str:
        """Следующий номер человека: P0001, P0002, … Номера удалённых не переиспользуются."""
        FamilyTree.objects.filter(pk=self.pk).update(next_number=models.F("next_number") + 1)
        self.refresh_from_db(fields=["next_number"])
        return f"P{self.next_number - 1:04d}"


class UserProfile(models.Model):
    """Настройки пользователя. Пока — язык интерфейса (выбирается при регистрации, меняется в «Аккаунте»)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile",
                                verbose_name=_("пользователь"))
    language = models.CharField(_("язык"), max_length=8, choices=settings.LANGUAGES, default="ru")

    class Meta:
        verbose_name = _("настройки пользователя")
        verbose_name_plural = _("настройки пользователей")

    def __str__(self):
        return str(self.user)

    @classmethod
    def of(cls, user) -> "UserProfile":
        profile, _created = cls.objects.get_or_create(user=user)
        return profile


def _invitation_code() -> str:
    return secrets.token_urlsafe(18)


def _invitation_expires():
    return timezone.now() + timedelta(days=14)


class Invitation(models.Model):
    """Приглашение — одноразовая ссылка на регистрацию. Создаётся в админке."""
    code = models.CharField(_("код"), max_length=40, unique=True, default=_invitation_code, editable=False)
    note = models.CharField(_("для кого"), max_length=120, blank=True,
                            help_text=_("Только для вас: кому отправили ссылку."))
    created = models.DateTimeField(_("создано"), auto_now_add=True)
    expires = models.DateTimeField(_("действует до"), default=_invitation_expires)
    used_by = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", verbose_name=_("кто зарегистрировался"), editable=False)
    used_at = models.DateTimeField(_("когда использовано"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("приглашение")
        verbose_name_plural = _("приглашения")
        ordering = ["-created"]

    def __str__(self):
        return self.note or _("Приглашение от %(date)s") % {"date": f"{self.created:%d.%m.%Y}"}

    @property
    def is_usable(self) -> bool:
        return self.used_at is None and self.expires > timezone.now()


class Person(models.Model):
    class Sex(models.TextChoices):
        MALE = "M", _("Мужской")
        FEMALE = "F", _("Женский")
        UNKNOWN = "U", _("Неизвестен")

    tree = models.ForeignKey(FamilyTree, on_delete=models.CASCADE, related_name="people",
                             verbose_name=_("древо"))
    code = models.CharField(_("номер"), max_length=12, blank=True, editable=False)
    given_name = models.CharField(_("имя"), max_length=120, blank=True)
    patronymic = models.CharField(_("отчество"), max_length=120, blank=True)
    birth_surname = models.CharField(
        _("фамилия при рождении"), max_length=120, blank=True,
        help_text=_("Для женщин — девичья. Смена фамилии хранится в вариантах имени."))
    sex = models.CharField(_("пол"), max_length=1, choices=Sex.choices, default=Sex.UNKNOWN)
    is_living = models.BooleanField(
        _("жив(а)"), default=False,
        help_text=_("Без даты смерти в древе: у живых «2007–», у остальных «1849–?»."))
    parent_family = models.ForeignKey(
        "Family", verbose_name=_("семья родителей"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="children")
    child_order = models.PositiveSmallIntegerField(
        _("порядок среди детей"), null=True, blank=True,
        help_text=_("Нужен, только если дат рождения нет, а порядок известен."))
    notes = models.TextField(_("краткое жизнеописание"), blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("человек")
        verbose_name_plural = _("люди")
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["tree", "code"], name="person_code_unique_in_tree")]

    def __str__(self):
        name = " ".join(x for x in (self.given_name, self.patronymic, self.birth_surname) if x)
        return f"{name or '?'} ({self.code})"

    def save(self, *args, **kwargs):
        if not self.code:      # собственная нумерация внутри древа: P0001, P0002, …
            self.code = self.tree.take_number()
        super().save(*args, **kwargs)

    @property
    def full_name(self) -> str:
        return " ".join(x for x in (self.given_name, self.patronymic, self.birth_surname) if x) or "?"

    @property
    def families(self):
        return Family.objects.filter(models.Q(partner1=self) | models.Q(partner2=self))

    def deletion_blockers(self) -> list[str]:
        from tree_engine.model import deletion_blockers
        from .bridge import build_tree
        return deletion_blockers(build_tree(self.tree), str(self.pk))


class Family(models.Model):
    """Союз (брак или пара). Партнёров 0–2: неизвестный родитель — пустое поле."""
    tree = models.ForeignKey(FamilyTree, on_delete=models.CASCADE, related_name="families",
                             verbose_name=_("древо"))
    partner1 = models.ForeignKey(Person, verbose_name=_("партнёр 1"), null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    partner2 = models.ForeignKey(Person, verbose_name=_("партнёр 2"), null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    notes = models.TextField(_("заметки"), blank=True)

    class Meta:
        verbose_name = _("семья")
        verbose_name_plural = _("семьи")

    def __str__(self):
        names = [str(p) for p in (self.partner1, self.partner2) if p]
        return " + ".join(names) or _("Семья №%(pk)s (родители неизвестны)") % {"pk": self.pk}

    def clean(self):
        if self.partner1_id and self.partner1_id == self.partner2_id:
            raise ValidationError(_("Партнёры должны быть разными людьми."))

    @property
    def partners(self):
        return [p for p in (self.partner1, self.partner2) if p]


class Place(models.Model):
    tree = models.ForeignKey(FamilyTree, on_delete=models.CASCADE, related_name="places",
                             verbose_name=_("древо"))
    name = models.CharField(_("название"), max_length=255,
                            help_text=_("Например: Boskovice, Blansko, Чехия"))
    latitude = models.FloatField(_("широта"), null=True, blank=True)
    longitude = models.FloatField(_("долгота"), null=True, blank=True)
    notes = models.TextField(_("заметки"), blank=True)

    class Meta:
        verbose_name = _("место")
        verbose_name_plural = _("места")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tree", "name"], name="place_name_unique_in_tree")]

    def __str__(self):
        return self.name


class Event(models.Model):
    """Событие или факт человека либо семьи."""
    class Kind(models.TextChoices):
        BIRTH = "BIRT", _("Рождение")
        CHRISTENING = "CHR", _("Крещение")
        DEATH = "DEAT", _("Смерть")
        BURIAL = "BURI", _("Погребение")
        MARRIAGE = "MARR", _("Брак")
        DIVORCE = "DIV", _("Развод")
        RESIDENCE = "RESI", _("Место жительства")
        EDUCATION = "EDUC", _("Образование")
        MILITARY = "MILI", _("Военная служба")
        EMIGRATION = "EMIG", _("Эмиграция")
        OCCUPATION = "OCCU", _("Профессия")
        RELIGION = "RELI", _("Вероисповедание")
        NATIONALITY = "NATI", _("Национальность")
        OTHER = "EVEN", _("Другое")

    KEY_KINDS = {"BIRT", "CHR", "DEAT", "BURI"}          # «ключевые сведения»
    FACT_KINDS = {"OCCU", "RELI", "NATI"}                # «факты» — без даты по смыслу

    person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.CASCADE,
                               related_name="events", verbose_name=_("человек"))
    family = models.ForeignKey(Family, null=True, blank=True, on_delete=models.CASCADE,
                               related_name="events", verbose_name=_("семья"))
    kind = models.CharField(_("тип"), max_length=4, choices=Kind.choices)
    title = models.CharField(_("название (для «Другое»)"), max_length=120, blank=True)
    date = models.CharField(
        _("дата"), max_length=60, blank=True,
        help_text=_("10.08.1962 · 1962 · около 1850 · до 1790 · после 1900 · 1850-1860"))
    sort_key = models.IntegerField(default=99999999, editable=False)
    place = models.ForeignKey(Place, null=True, blank=True, on_delete=models.SET_NULL,
                              verbose_name=_("место"))
    value = models.CharField(_("значение"), max_length=255, blank=True,
                             help_text=_("Для фактов: например, «кузнец»"))
    description = models.TextField(_("описание"), blank=True)

    class Meta:
        verbose_name = _("событие / факт")
        verbose_name_plural = _("события и факты")
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
        return FuzzyDate(self.date).display(get_language()) if self.date else ""

    @property
    def label(self) -> str:
        return self.title if self.kind == self.Kind.OTHER and self.title else self.get_kind_display()


class PersonName(models.Model):
    """Варианты имени: в браке, после развода, транслитерация, при крещении…"""
    class Kind(models.TextChoices):
        MARRIED = "married", _("В браке")
        CHANGED = "changed", _("Смена фамилии")
        ALIAS = "alias", _("Также известен как")
        TRANSLIT = "translit", _("Другое написание / транслитерация")
        RELIGIOUS = "religious", _("Имя при крещении")

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="names")
    kind = models.CharField(_("тип"), max_length=12, choices=Kind.choices, default=Kind.ALIAS)
    given_name = models.CharField(_("имя"), max_length=120, blank=True)
    patronymic = models.CharField(_("отчество"), max_length=120, blank=True)
    surname = models.CharField(_("фамилия"), max_length=120, blank=True)
    date = models.CharField(_("с какого времени"), max_length=60, blank=True)
    note = models.CharField(_("примечание"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("вариант имени")
        verbose_name_plural = _("варианты имени")

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
        SOURCE = "source", _("Источник")
        MEMORY = "memory", _("Воспоминание")

    class Kind(models.TextChoices):
        BIRTH = "birth", _("Запись о рождении")
        BAPTISM = "baptism", _("Запись о крещении")
        MARRIAGE = "marriage", _("Запись о браке")
        DEATH = "death", _("Запись о смерти")
        CENSUS = "census", _("Перепись")
        PHOTO = "photo", _("Фотография")
        LETTER = "letter", _("Письмо / личный документ")
        OTHER = "other", _("Другое")

    tree = models.ForeignKey(FamilyTree, on_delete=models.CASCADE, related_name="sources",
                             verbose_name=_("древо"))
    category = models.CharField(_("раздел"), max_length=8, choices=Category.choices,
                                default=Category.SOURCE)
    title = models.CharField(_("название"), max_length=255)
    kind = models.CharField(_("тип"), max_length=12, choices=Kind.choices, default=Kind.OTHER)
    date = models.CharField(_("дата события"), max_length=60, blank=True)
    created = models.DateTimeField(_("добавлен"), auto_now_add=True, null=True)
    repository = models.CharField(_("где хранится"), max_length=255, blank=True,
                                  help_text=_("Архив, книга, семейный альбом…"))
    reference = models.CharField(_("шифр / ссылка"), max_length=500, blank=True)
    notes = models.TextField(_("заметки / расшифровка"), blank=True)

    class Meta:
        verbose_name = _("источник")
        verbose_name_plural = _("источники")
        ordering = ["title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.date)
        super().save(*args, **kwargs)

    @property
    def date_display(self) -> str:
        return FuzzyDate(self.date).display(get_language()) if self.date else ""

    @property
    def sort_key(self) -> int:
        return FuzzyDate(self.date).sort_int if self.date else 99999999


class SourceFile(models.Model):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(_("файл"), upload_to="sources/%Y/")
    caption = models.CharField(_("подпись"), max_length=255, blank=True)
    sha256 = models.CharField(_("отпечаток файла"), max_length=64, blank=True, db_index=True, editable=False,
                              help_text=_("По нему узнаётся повторная загрузка того же файла."))

    class Meta:
        verbose_name = _("файл")
        verbose_name_plural = _("файлы (сканы, фото)")

    def __str__(self):
        return self.caption or self.file.name

    @property
    def is_image(self) -> bool:
        return self.file.name.lower().rsplit(".", 1)[-1] in {"jpg", "jpeg", "png", "gif", "webp", "tif", "tiff"}


class Citation(models.Model):
    """Связь «источник ↔ человек» (и, по желанию, конкретное событие)."""
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="citations",
                               verbose_name=_("источник"))
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="citations",
                               verbose_name=_("человек"))
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="citations", verbose_name=_("событие"))
    detail = models.CharField(_("где именно"), max_length=255, blank=True,
                              help_text=_("Страница, строка, кто на фото слева направо…"))

    class Meta:
        verbose_name = _("ссылка на источник")
        verbose_name_plural = _("ссылки на источники")
        constraints = [models.UniqueConstraint(fields=["source", "person", "event"],
                                               name="unique_citation")]

    def __str__(self):
        return f"{self.source} → {self.person}"
