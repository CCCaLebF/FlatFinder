from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "backend.core"
    # The label stays "core" so table names and migration history are unchanged.
    label = "core"
    verbose_name = "FlatFinder"
