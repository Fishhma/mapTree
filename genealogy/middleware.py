"""Язык интерфейса.

До входа язык выбирает LocaleMiddleware: cookie (переключатель RU · EN · CS на
страницах входа и регистрации), иначе язык браузера; если браузер не знает ни
одного из наших языков — английский (settings.FALLBACK_LANGUAGE). После входа —
язык из настроек пользователя (UserProfile.language); он же записывается в
cookie, чтобы и после выхода страница входа была на привычном языке.
"""
from django.conf import settings
from django.utils import translation
from django.utils.translation.trans_real import get_supported_language_variant, parse_accept_lang_header

from .models import UserProfile


def browser_language(request) -> str | None:
    """Первый из наших языков в заголовке Accept-Language браузера (или None)."""
    for code, _quality in parse_accept_lang_header(request.headers.get("Accept-Language", "")):
        if code == "*":
            continue
        try:
            return get_supported_language_variant(code)
        except LookupError:
            continue
    return None


class UserLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            language = UserProfile.of(request.user).language
        elif (settings.LANGUAGE_COOKIE_NAME not in request.COOKIES and request.headers.get("Accept-Language")
              and browser_language(request) is None):
            language = settings.FALLBACK_LANGUAGE                # браузер на чужом для нас языке
        else:
            language = None                                       # решил LocaleMiddleware
        if language:
            translation.activate(language)
            request.LANGUAGE_CODE = language
        response = self.get_response(request)
        if request.user.is_authenticated:
            language = translation.get_language()    # мог смениться на странице «Аккаунт»
            if request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME) != language:
                response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language,
                                    max_age=settings.LANGUAGE_COOKIE_AGE, samesite="Lax")
        return response
