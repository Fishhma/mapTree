from django.db import migrations
from django.db.models import Q


def drop_hollow_families(apps, schema_editor):
    """Убрать оставшиеся от удалённых супругов семьи: один партнёр и ни одного ребёнка."""
    Family = apps.get_model("genealogy", "Family")
    Family.objects.filter(children=None).filter(Q(partner1=None) | Q(partner2=None)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('genealogy', '0003_materials'),
    ]

    operations = [
        migrations.RunPython(drop_hollow_families, migrations.RunPython.noop),
    ]
