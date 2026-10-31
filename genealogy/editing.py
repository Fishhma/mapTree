"""Изменение данных: добавление родственников, правка и удаление человека, материалы.

«+» на карточке: ребёнок, супруг(а), родитель, родной брат или сестра — всегда НОВЫЙ человек
(связывание с уже существующим — отдельный шаг). Все поля необязательны.
Связи строятся только через семьи (союзы), как и везде в проекте.
"""
import hashlib
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Citation, Event, Family, Person, Place, Source, SourceFile

RELATIONS = ("child", "spouse", "parent", "sibling")


class EditError(ValueError):
    """Понятная пользователю причина, почему действие невозможно."""


def _text(data: dict, key: str) -> str:
    value = data.get(key) or ""
    return " ".join(str(value).split())


def find_or_create_place(name: str) -> Place | None:
    if not name:
        return None
    return Place.objects.filter(name__iexact=name).first() or Place.objects.create(name=name)


def _create_person(data: dict) -> Person:
    sex = data.get("sex") if data.get("sex") in Person.Sex.values else Person.Sex.UNKNOWN
    person = Person(given_name=_text(data, "given_name"), patronymic=_text(data, "patronymic"),
                    birth_surname=_text(data, "birth_surname"), sex=sex,
                    is_living=bool(data.get("is_living")))
    person.full_clean(exclude=["code", "parent_family"])
    person.save()
    date, place = _text(data, "birth_date"), _text(data, "birth_place")
    if date or place:
        Event.objects.create(person=person, kind=Event.Kind.BIRTH, date=date,
                             place=find_or_create_place(place))
    return person


@transaction.atomic
def add_relative(person: Person, relation: str, data: dict, family_id=None) -> Person:
    """Создать нового родственника для `person` и связать его через семью.

    child   — в семью `family_id` (союз этого человека) или в новую семью,
              где второй родитель неизвестен;
    spouse  — новая семья (повторный брак — просто ещё одна семья);
    parent  — на свободное место в семье родителей (создаётся, если её нет);
    sibling — в семью родителей (если родители неизвестны — семья без партнёров).
    """
    if relation not in RELATIONS:
        raise EditError("Неизвестный вид родства.")
    parents = person.parent_family
    if relation == "parent" and parents and parents.partner1_id and parents.partner2_id:
        raise EditError("У человека уже указаны оба родителя.")
    family = None
    if relation == "child" and family_id:
        family = person.families.filter(pk=family_id).first()
        if family is None:
            raise EditError("Этот союз не относится к выбранному человеку.")

    new = _create_person(data)

    if relation == "child":
        new.parent_family = family or Family.objects.create(partner1=person)
        new.save(update_fields=["parent_family"])
    elif relation == "spouse":
        Family.objects.create(partner1=person, partner2=new)
    elif relation == "parent":
        if parents is None:
            person.parent_family = Family.objects.create(partner1=new)
            person.save(update_fields=["parent_family"])
        elif not parents.partner1_id:
            parents.partner1 = new
            parents.save(update_fields=["partner1"])
        else:
            parents.partner2 = new
            parents.save(update_fields=["partner2"])
    else:  # sibling
        if parents is None:
            parents = Family.objects.create()
            person.parent_family = parents
            person.save(update_fields=["parent_family"])
        new.parent_family = parents
        new.save(update_fields=["parent_family"])
    return new


def save_key_events(person: Person, events: dict[str, Event], data: dict) -> None:
    """Записать дату и место ключевых событий (рождение, крещение, смерть, погребение).

    `events` — уже существующие события по виду, `data` — cleaned_data формы.
    Если дату и место стёрли, событие удаляется, но только когда в нём больше
    ничего нет (описания, значения, ссылок на источники).
    """
    for kind in ("BIRT", "CHR", "DEAT", "BURI"):
        date, place = _text(data, f"{kind}_date"), _text(data, f"{kind}_place")
        event = events.get(kind)
        if event is None:
            if date or place:
                Event.objects.create(person=person, kind=kind, date=date,
                                     place=find_or_create_place(place))
            continue
        if not date and not place and not event.value and not event.description \
                and not event.citations.exists():
            event.delete()
            continue
        event.date, event.place = date, find_or_create_place(place)
        event.save()


def deletion_summary(person: Person) -> list[str]:
    """Что исчезнет вместе с человеком — показывается перед удалением."""
    items = []
    for count, word in ((person.events.count(), "событий и фактов"),
                        (person.names.count(), "вариантов имени"),
                        (person.citations.count(), "ссылок на источники (сами источники останутся)")):
        if count:
            items.append(f"{word}: {count}")
    return items


@transaction.atomic
def delete_person(person: Person, typed_code: str) -> None:
    """Удаление — второе подтверждение: нужно ввести номер именно этого человека."""
    blockers = person.deletion_blockers()
    if blockers:
        raise EditError("Удалить нельзя: " + "; ".join(blockers) + ".")
    if typed_code.strip().upper() != person.code:
        raise EditError(f"Номер не совпадает. Чтобы удалить, введите {person.code}.")
    person.delete()


IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "tif", "tiff", "bmp"}


def file_sha256(upload) -> str:
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


@transaction.atomic
def add_material(person: Person, category: str, upload, title: str = "", date: str = "") -> tuple[Source, bool]:
    """Источник или воспоминание: изображение + название + дата события.

    Один и тот же файл хранится один раз: если он уже загружен в этот раздел,
    существующий материал просто привязывается к человеку. Возвращает (материал, был_ли_уже).
    """
    if category not in Source.Category.values:
        raise EditError("Неизвестный раздел.")
    if upload is None:
        raise EditError("Выберите изображение.")
    if Path(upload.name).suffix.lower().lstrip(".") not in IMAGE_EXTENSIONS:
        raise EditError("Можно загрузить только изображение: JPG, PNG, GIF, WEBP, TIFF или BMP.")
    digest = file_sha256(upload)
    same = SourceFile.objects.select_related("source").filter(sha256=digest, source__category=category).first()
    if same:
        source, existed = same.source, True
    else:
        source = Source.objects.create(
            category=category, title=" ".join(title.split()) or Path(upload.name).stem,
            kind=Source.Kind.PHOTO if category == Source.Category.MEMORY else Source.Kind.OTHER,
            date=" ".join(date.split()))
        SourceFile.objects.create(source=source, file=upload, sha256=digest)
        existed = False
    Citation.objects.get_or_create(source=source, person=person, event=None)
    return source, existed


def error_text(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return " ".join(exc.messages)
    return str(exc)
