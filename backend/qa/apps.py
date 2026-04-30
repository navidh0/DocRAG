# qa/apps.py
from django.apps import AppConfig


class QaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "qa"

    def ready(self):
        pass # No signal registration needed at this time