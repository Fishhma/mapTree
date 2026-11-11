"""Формы страницы человека (/people/P0001/). Все поля необязательны."""
from django import forms
from django.utils.translation import get_language, gettext_lazy

from tree_engine.model import to_user_date

from .editing import find_or_create_place
from .models import Event, Person, PersonName

KEY_KINDS = ("BIRT", "CHR", "DEAT", "BURI")
# Подсказка под полями дат — на языке интерфейса (а понимаются слова всех трёх языков).
DATE_HINT = gettext_lazy("10.08.1962 · около 1850 · до 1790 · после 1900 · 1850-52 · 1850/51")


class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ["given_name", "patronymic", "birth_surname", "sex", "is_living", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 8}),
        }


class KeyEventsForm(forms.Form):
    """Рождение, крещение, смерть, погребение: дата и место каждого.

    Редактируется первое событие каждого вида (в GEDCOM их бывает несколько).
    """

    def __init__(self, *args, person: Person, **kwargs):
        super().__init__(*args, **kwargs)
        self.person = person
        self.events = {}
        for e in person.events.select_related("place").filter(kind__in=KEY_KINDS):
            self.events.setdefault(e.kind, e)
        for kind in KEY_KINDS:
            event = self.events.get(kind)
            self.fields[f"{kind}_date"] = forms.CharField(
                label="дата", required=False, max_length=60,
                initial=to_user_date(event.date, get_language()) if event and event.date else "",
                widget=forms.TextInput(attrs={"autocomplete": "off"}))
            self.fields[f"{kind}_place"] = forms.CharField(
                label="место", required=False, max_length=255,
                initial=event.place.name if event and event.place else "",
                widget=forms.TextInput(attrs={"list": "places", "autocomplete": "off"}))

    def rows(self):
        """Для шаблона: (название, поле даты, поле места) по каждому виду."""
        return [(Event.Kind(kind).label, self[f"{kind}_date"], self[f"{kind}_place"])
                for kind in KEY_KINDS]


# ---------- «Другие сведения»: события, факты, варианты имени ----------
OTHER_KINDS = [k for k in Event.Kind if k.value not in (*KEY_KINDS, "MARR", "DIV")]


class OtherEventForm(forms.ModelForm):
    """Событие или факт (кроме ключевых). Место вводится текстом и находится/создаётся само."""
    place_name = forms.CharField(label="место", required=False, max_length=255,
                                 widget=forms.TextInput(attrs={"list": "places", "autocomplete": "off"}))

    class Meta:
        model = Event
        fields = ["kind", "title", "date", "place_name", "value", "description"]
        labels = {"title": "название", "value": "значение"}
        widgets = {"date": forms.TextInput(attrs={"autocomplete": "off"}),
                   "description": forms.TextInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [("", "— выберите —")] + [(k.value, k.label) for k in OTHER_KINDS]
        if self.instance.pk:
            self.initial["date"] = to_user_date(self.instance.date, get_language()) if self.instance.date else ""
            self.initial["place_name"] = self.instance.place.name if self.instance.place else ""

    def save(self, commit=True):
        self.instance.place = find_or_create_place(self.instance.person.tree,
                                                   " ".join(self.cleaned_data["place_name"].split()))
        return super().save(commit)


class NameForm(forms.ModelForm):
    class Meta:
        model = PersonName
        fields = ["kind", "given_name", "patronymic", "surname", "date", "note"]
        widgets = {"date": forms.TextInput(attrs={"autocomplete": "off"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.date:
            self.initial["date"] = to_user_date(self.instance.date, get_language())


EventFormSet = forms.inlineformset_factory(Person, Event, form=OtherEventForm, fk_name="person",
                                           extra=0, can_delete=True)
NameFormSet = forms.inlineformset_factory(Person, PersonName, form=NameForm, extra=0, can_delete=True)


def person_forms(person: Person, data=None) -> dict:
    """Все формы страницы человека; без data — пустые (показ), с data — для сохранения."""
    return {
        "form": PersonForm(data, instance=person),
        "events_form": KeyEventsForm(data, person=person),
        "other_events": EventFormSet(
            data, instance=person, prefix="events",
            queryset=person.events.exclude(kind__in=(*KEY_KINDS, "MARR", "DIV")).select_related("place")),
        "names": NameFormSet(data, instance=person, prefix="names"),
    }
