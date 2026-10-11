from django.apps import AppConfig


class AppConfig(AppConfig):
    name = 'app'

    def ready(self):
        from .services.moderation.capture import connect_signals
        connect_signals()

        from .services.establishments.reverse_geocoding import connect_signals as connect_geocoding_signals
        connect_geocoding_signals()

        from .services.members.welcome import connect_signals as connect_welcome_signals
        connect_welcome_signals()

        from .services.catalog import embeddings
        from .services.messaging import notification_policy
        from .services.establishments import place_geocoding
        from .models import notifications
        embeddings.connect_signals()
        place_geocoding.connect_signals()
        notifications.use_admission_policy(notification_policy.filter_allowed)
