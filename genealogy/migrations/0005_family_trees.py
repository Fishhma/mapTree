"""Своё древо у каждого пользователя.

Все существующие люди, семьи, места и материалы переходят в одно древо, владелец —
первый администратор (superuser). Опорный человек — из прежних «настроек древа»,
нумерация P0001… продолжается с прежнего наибольшего номера.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import genealogy.models

DATA_MODELS = ("Person", "Family", "Place", "Source")


def move_data_to_tree(apps, schema_editor):
    get = lambda name: apps.get_model("genealogy", name)  # noqa: E731
    if not any(get(name).objects.exists() for name in DATA_MODELS):
        return
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    owner = User.objects.filter(is_superuser=True).order_by("id").first()
    old = get("TreeSettings").objects.first()
    numbers = [int(code[1:]) for code in get("Person").objects.values_list("code", flat=True)
               if code[1:].isdigit()]
    tree = get("FamilyTree").objects.create(owner=owner, root_person_id=old.root_person_id if old else None,
                                            next_number=max(numbers, default=0) + 1)
    for name in DATA_MODELS:
        get(name).objects.update(tree=tree)


def back_to_settings(apps, schema_editor):
    tree = apps.get_model("genealogy", "FamilyTree").objects.order_by("id").first()
    if tree:
        apps.get_model("genealogy", "TreeSettings").objects.update_or_create(
            pk=1, defaults={"root_person_id": tree.root_person_id})


def tree_field(related_name, null):
    return models.ForeignKey(null=null, on_delete=django.db.models.deletion.CASCADE,
                             related_name=related_name, to="genealogy.familytree", verbose_name="древо")


class Migration(migrations.Migration):

    dependencies = [
        ("genealogy", "0004_drop_hollow_families"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FamilyTree",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("next_number", models.PositiveIntegerField(
                    default=1, help_text="Номер, который получит следующий новый человек.",
                    verbose_name="следующий номер")),
                ("created", models.DateTimeField(auto_now_add=True, verbose_name="создано")),
                ("owner", models.OneToOneField(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name="family_tree", to=settings.AUTH_USER_MODEL, verbose_name="владелец")),
                ("root_person", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+",
                    to="genealogy.person", verbose_name="опорный человек (поколение 1)")),
            ],
            options={"verbose_name": "древо", "verbose_name_plural": "древа"},
        ),
        migrations.CreateModel(
            name="Invitation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(default=genealogy.models._invitation_code, editable=False,
                                          max_length=40, unique=True, verbose_name="код")),
                ("note", models.CharField(blank=True, help_text="Только для вас: кому отправили ссылку.",
                                          max_length=120, verbose_name="для кого")),
                ("created", models.DateTimeField(auto_now_add=True, verbose_name="создано")),
                ("expires", models.DateTimeField(default=genealogy.models._invitation_expires,
                                                 verbose_name="действует до")),
                ("used_at", models.DateTimeField(blank=True, editable=False, null=True,
                                                 verbose_name="когда использовано")),
                ("used_by", models.OneToOneField(
                    blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="кто зарегистрировался")),
            ],
            options={"verbose_name": "приглашение", "verbose_name_plural": "приглашения",
                     "ordering": ["-created"]},
        ),
        migrations.AddField(model_name="person", name="tree", field=tree_field("people", True)),
        migrations.AddField(model_name="family", name="tree", field=tree_field("families", True)),
        migrations.AddField(model_name="place", name="tree", field=tree_field("places", True)),
        migrations.AddField(model_name="source", name="tree", field=tree_field("sources", True)),
        migrations.RunPython(move_data_to_tree, back_to_settings),
        migrations.AlterField(model_name="person", name="tree", field=tree_field("people", False)),
        migrations.AlterField(model_name="family", name="tree", field=tree_field("families", False)),
        migrations.AlterField(model_name="place", name="tree", field=tree_field("places", False)),
        migrations.AlterField(model_name="source", name="tree", field=tree_field("sources", False)),
        migrations.AlterField(
            model_name="person", name="code",
            field=models.CharField(blank=True, editable=False, max_length=12, verbose_name="номер")),
        migrations.AlterField(
            model_name="place", name="name",
            field=models.CharField(help_text="Например: Boskovice, Blansko, Чехия", max_length=255,
                                   verbose_name="название")),
        migrations.AddConstraint(
            model_name="person",
            constraint=models.UniqueConstraint(fields=("tree", "code"), name="person_code_unique_in_tree")),
        migrations.AddConstraint(
            model_name="place",
            constraint=models.UniqueConstraint(fields=("tree", "name"), name="place_name_unique_in_tree")),
        migrations.DeleteModel(name="TreeSettings"),
    ]
