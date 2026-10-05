from django.contrib import admin

from .models import ParentChild, Partnership, Person, SiblingRelationship


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("full_name", "birth_date", "death_date", "sex")
    list_filter = ("sex",)
    search_fields = ("given_name", "family_name")


@admin.register(Partnership)
class PartnershipAdmin(admin.ModelAdmin):
    list_display = ("partner_a", "partner_b", "start_date", "end_date", "label")
    autocomplete_fields = ("partner_a", "partner_b")
    search_fields = ("partner_a__given_name", "partner_a__family_name", "partner_b__given_name", "partner_b__family_name", "label")


@admin.register(ParentChild)
class ParentChildAdmin(admin.ModelAdmin):
    list_display = ("parent", "child", "partnership", "birth_order")
    list_filter = ("partnership",)
    autocomplete_fields = ("parent", "child", "partnership")


@admin.register(SiblingRelationship)
class SiblingRelationshipAdmin(admin.ModelAdmin):
    list_display = ("person_a", "person_b", "label")
    autocomplete_fields = ("person_a", "person_b")
    search_fields = ("person_a__given_name", "person_a__family_name", "person_b__given_name", "person_b__family_name")
