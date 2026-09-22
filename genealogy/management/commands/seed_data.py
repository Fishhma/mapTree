from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from genealogy.models import ParentChild, Partnership, Person


class Command(BaseCommand):
    help = "Reset and seed the four-person fictional genealogy demo."

    @transaction.atomic
    def handle(self, *args, **options):
        ParentChild.objects.all().delete()
        Partnership.objects.all().delete()
        Person.objects.all().delete()

        river = Person.objects.create(
            given_name="Mara", family_name="River", birth_date=date(1978, 4, 12), sex=Person.Sex.FEMALE
        )
        sol = Person.objects.create(
            given_name="Jonas", family_name="River", birth_date=date(1976, 9, 3), sex=Person.Sex.MALE
        )
        partnership = Partnership.objects.create(
            partner_a=river, partner_b=sol, start_date=date(2001, 6, 14), label="River household"
        )
        noa = Person.objects.create(
            given_name="Iris", family_name="River", birth_date=date(2004, 2, 19), sex=Person.Sex.FEMALE
        )
        eli = Person.objects.create(
            given_name="Theo", family_name="River", birth_date=date(2007, 11, 8), sex=Person.Sex.MALE
        )
        ParentChild.objects.bulk_create(
            [
                ParentChild(parent=river, child=noa, partnership=partnership, birth_order=1),
                ParentChild(parent=sol, child=noa, partnership=partnership, birth_order=1),
                ParentChild(parent=river, child=eli, partnership=partnership, birth_order=2),
                ParentChild(parent=sol, child=eli, partnership=partnership, birth_order=2),
            ]
        )
        self.stdout.write(self.style.SUCCESS("Seeded Mara, Jonas, Iris, and Theo River."))
