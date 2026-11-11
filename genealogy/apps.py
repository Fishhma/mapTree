from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class GenealogyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "genealogy"
    verbose_name = _("Генеалогия")

    def ready(self):
        from . import signals  # noqa: F401
        from .i18n import compile_all
        try:
            compile_all()                 # .po новее .mo → пересобрать (GNU gettext не нужен)
        except OSError:
            pass                          # папка только для чтения — берём то, что есть
