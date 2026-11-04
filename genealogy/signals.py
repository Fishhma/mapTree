from django.db.models import Q
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Family, Person


def drop_hollow_families() -> int:
    """Убрать «пустые» семьи: без детей и меньше чем с двумя партнёрами.

    Такая семья ничего не значит (брак — это двое, а одинокий родитель — это дети),
    зато в древе от неё торчит отросток линии брака. Возвращает, сколько удалено.
    """
    hollow = Family.objects.filter(children=None).filter(Q(partner1=None) | Q(partner2=None))
    return hollow.delete()[1].get("genealogy.Family", 0)


@receiver(post_delete, sender=Person)
def drop_empty_families(sender, instance, **kwargs):
    """После удаления человека убираем семьи, от которых остался только один партнёр без детей."""
    drop_hollow_families()
