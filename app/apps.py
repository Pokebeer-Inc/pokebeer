from django.apps import AppConfig


class AppConfig(AppConfig):
    name = 'app'

    def ready(self):
        from .services.moderation.capture import connect_signals
        connect_signals()

        from .services.reverse_geocoding import connect_signals as connect_geocoding_signals
        connect_geocoding_signals()

        from .services.welcome import connect_signals as connect_welcome_signals
        connect_welcome_signals()
