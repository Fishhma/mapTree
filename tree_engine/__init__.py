"""Ядро генеалогического древа: модель, импорт GEDCOM, поколения, раскладка.

Не зависит от Django — его можно тестировать и запускать отдельно.

Сообщения ядра пишутся по-русски через _(): без Django они так и остаются,
а сайт при запуске подставляет свой перевод (set_translator(gettext)).
"""
_translator = None


def set_translator(func) -> None:
    """Подключить перевод сообщений ядра (например, django.utils.translation.gettext)."""
    global _translator
    _translator = func


def _(message: str) -> str:
    return _translator(message) if _translator else message
