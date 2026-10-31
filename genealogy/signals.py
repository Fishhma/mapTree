from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Family, Person


@receiver(post_delete, sender=Person)
def drop_empty_families(sender, instance, **kwargs):
    """После удаления человека убираем семьи, где не осталось ни партнёров, ни детей."""
    Family.objects.filter(partner1=None, partner2=None, children=None).delete()
