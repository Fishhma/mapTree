"""Формы страницы человека (/people/P0001/). Все поля необязательны."""
from django import forms

from tree_engine.model import to_user_date

from .models import Event, Person

KEY_KINDS = ("BIRT", "CHR", "DEAT", "BURI")
DATE_HINT = "10.08.1962 · около 1850 · до 1790 · 1850-1860"


class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ["given_name", "patronymic", "birth_surname", "sex", "notes"]
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
                initial=to_user_date(event.date) if event and event.date else "",
                widget=forms.TextInput(attrs={"autocomplete": "off"}))
            self.fields[f"{kind}_place"] = forms.CharField(
                label="место", required=False, max_length=255,
                initial=event.place.name if event and event.place else "",
                widget=forms.TextInput(attrs={"list": "places", "autocomplete": "off"}))

    def rows(self):
        """Для шаблона: (название, поле даты, поле места) по каждому виду."""
        return [(Event.Kind(kind).label, self[f"{kind}_date"], self[f"{kind}_place"])
                for kind in KEY_KINDS]
