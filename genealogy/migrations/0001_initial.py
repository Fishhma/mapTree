from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Person",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("given_name", models.CharField(max_length=80)),
                ("family_name", models.CharField(max_length=80)),
                ("birth_date", models.DateField(blank=True, null=True)),
                ("death_date", models.DateField(blank=True, null=True)),
                ("sex", models.CharField(choices=[("F", "Female"), ("M", "Male"), ("U", "Unspecified")], default="U", max_length=1)),
                ("notes", models.TextField(blank=True)),
            ],
            options={"ordering": ["birth_date", "family_name", "given_name"]},
        ),
        migrations.CreateModel(
            name="Partnership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("start_date", models.DateField(blank=True, null=True)),
                ("end_date", models.DateField(blank=True, null=True)),
                ("label", models.CharField(blank=True, max_length=120)),
                ("partner_a", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="partnerships_as_a", to="genealogy.person")),
                ("partner_b", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="partnerships_as_b", to="genealogy.person")),
            ],
            options={
                "ordering": ["start_date", "id"],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("partner_a", models.F("partner_b")), _negated=True), name="partnership_partners_differ"),
                    models.UniqueConstraint(fields=("partner_a", "partner_b"), name="unique_ordered_partnership"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ParentChild",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("birth_order", models.PositiveSmallIntegerField(default=1, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(99)])),
                ("child", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="parent_links", to="genealogy.person")),
                ("parent", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="children_links", to="genealogy.person")),
                ("partnership", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="parent_child_links", to="genealogy.partnership")),
            ],
            options={
                "ordering": ["child__birth_date", "birth_order", "parent_id"],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("parent", models.F("child")), _negated=True), name="parent_child_people_differ"),
                    models.UniqueConstraint(fields=("parent", "child"), name="unique_parent_child_link"),
                ],
            },
        ),
    ]
