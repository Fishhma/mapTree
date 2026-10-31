"""Админка Django — временный редактор, пока не сделаны свои формы на странице древа."""
from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html

from tree_engine.model import to_user_date

from .models import (Citation, Event, Family, Person, PersonName, Place, Source, SourceFile,
                     TreeSettings)


class FriendlyDateForm(forms.ModelForm):
    """Даты в формах показываются как «10.08.1962», хранятся в формате GEDCOM."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "date" in self.fields and self.instance.pk and self.instance.date:
            self.initial["date"] = to_user_date(self.instance.date)


class PersonEventInline(admin.TabularInline):
    model = Event
    form = FriendlyDateForm
    fk_name = "person"
    fields = ("kind", "title", "date", "place", "value", "description")
    autocomplete_fields = ("place",)
    extra = 0


class FamilyEventInline(PersonEventInline):
    fk_name = "family"


class NameInline(admin.TabularInline):
    model = PersonName
    form = FriendlyDateForm
    extra = 0


class PersonCitationInline(admin.TabularInline):
    model = Citation
    fields = ("source", "event", "detail")
    autocomplete_fields = ("source",)
    extra = 0

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "event":   # только события этого человека
            pk = request.resolver_match.kwargs.get("object_id")
            kwargs["queryset"] = Event.objects.filter(person_id=pk) if pk else Event.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ChildInline(admin.TabularInline):
    model = Person
    fk_name = "parent_family"
    fields = ("given_name", "patronymic", "birth_surname", "sex", "child_order")
    extra = 0
    verbose_name = "ребёнок"
    verbose_name_plural = "дети этой семьи"
    show_change_link = True


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("code", "given_name", "patronymic", "birth_surname", "sex", "parent_family")
    search_fields = ("code", "given_name", "patronymic", "birth_surname", "names__surname")
    list_filter = ("sex",)
    autocomplete_fields = ("parent_family",)
    fields = ("code", "given_name", "patronymic", "birth_surname", "sex",
              "parent_family", "child_order", "notes")
    readonly_fields = ("code",)
    inlines = [PersonEventInline, NameInline, PersonCitationInline]
    actions = None   # без массового удаления: каждого — только через проверку

    def has_delete_permission(self, request, obj=None):
        if obj is None:
            return super().has_delete_permission(request)
        return super().has_delete_permission(request, obj) and not obj.deletion_blockers()

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        if obj and request.method == "GET":
            blockers = obj.deletion_blockers()
            if blockers:
                messages.warning(request, "Удалить нельзя: " + "; ".join(blockers) + ".")
        return super().change_view(request, object_id, form_url, extra_context)


@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ("__str__", "children_count")
    search_fields = ("partner1__given_name", "partner1__birth_surname", "partner1__code",
                     "partner2__given_name", "partner2__birth_surname", "partner2__code")
    autocomplete_fields = ("partner1", "partner2")
    inlines = [ChildInline, FamilyEventInline]

    @admin.display(description="детей")
    def children_count(self, obj):
        return obj.children.count()


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ("name", "latitude", "longitude")
    search_fields = ("name",)


class SourceFileInline(admin.TabularInline):
    model = SourceFile
    fields = ("file", "caption", "preview")
    readonly_fields = ("preview",)
    extra = 1

    @admin.display(description="просмотр")
    def preview(self, obj):
        if obj.pk and obj.is_image:
            return format_html('<img src="{}" style="max-height:90px">', obj.file.url)
        return ""


class SourceCitationInline(admin.TabularInline):
    model = Citation
    fields = ("person", "event", "detail")
    autocomplete_fields = ("person",)
    extra = 1
    verbose_name_plural = "кто есть в этом источнике"


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    form = FriendlyDateForm
    list_display = ("title", "kind", "date", "repository")
    list_filter = ("kind",)
    search_fields = ("title", "repository", "reference", "notes")
    inlines = [SourceFileInline, SourceCitationInline]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    form = FriendlyDateForm
    list_display = ("__str__", "person", "family", "place")
    list_filter = ("kind",)
    search_fields = ("person__given_name", "person__birth_surname", "place__name")
    autocomplete_fields = ("person", "family", "place")


@admin.register(TreeSettings)
class TreeSettingsAdmin(admin.ModelAdmin):
    autocomplete_fields = ("root_person",)

    def has_add_permission(self, request):
        return not TreeSettings.objects.exists()
