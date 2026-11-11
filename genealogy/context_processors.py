from django.conf import settings


def languages(request):
    """Названия языков как есть — каждый на самом себе («Русский · English · Čeština»).

    Тег {% get_available_languages %} переводил бы их на текущий язык («anglicky»).
    """
    return {"LANGUAGE_NAMES": settings.LANGUAGES}
