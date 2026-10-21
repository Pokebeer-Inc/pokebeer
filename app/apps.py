from importlib import import_module

from django.apps import AppConfig

# Services qui réagissent aux changements de modèles : chacun déclare ses signaux dans une fonction `connect_signals()`. Le modèle ne fait
# que constater (adresse changée, vecteur périmé…) ; l'appel au service (réseau, fichiers, caches) est branché ici, au démarrage.
SIGNAL_MODULES = (
    'app.services.moderation.capture',
    'app.services.establishments.reverse_geocoding',
    'app.services.establishments.place_geocoding',
    'app.services.establishments.place_directory',
    'app.services.members.welcome',
    'app.services.catalog.embeddings',
    'app.services.catalog.styles',
    'app.services.catalog.style_registry',
    'app.services.common.images',
)


class AppConfig(AppConfig):
    name = 'app'

    def ready(self):
        for module in SIGNAL_MODULES:
            import_module(module).connect_signals()
