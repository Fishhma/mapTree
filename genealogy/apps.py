from django.apps import AppConfig


class GenealogyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "genealogy"
    verbose_name = "Генеалогия"

    def ready(self):
        from . import signals  # noqa: F401
