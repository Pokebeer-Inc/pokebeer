from django.apps import AppConfig


class AppConfig(AppConfig):
    name = 'app'

    def ready(self):
        from .services.moderation.capture import connect_signals
        connect_signals()
