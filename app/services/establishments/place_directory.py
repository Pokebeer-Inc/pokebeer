"""Annuaire des bars et brasseries localisés, pour classer les lieux par distance « Près de moi ».

La position de l'appareil n'est jamais envoyée au serveur : celui-ci publie la liste (données déjà publiques des fiches) et le
navigateur calcule les distances. Pas de position en paramètre, donc rien à journaliser, à conserver ni à protéger côté serveur.
"""
from django.core.cache import cache
from django.db.models.signals import post_delete, post_save

from .places import PLACE_KINDS

MAX_PLACES = 5000  # borne de la taille de la réponse ; au-delà, il faudra découper par zone
CACHE_KEY = 'places-directory'
CACHE_SECONDS = 300  # une fiche modifiée apparaît au plus tard après ce délai
MARKERS_CACHE_KEY = 'places-map-markers'


TROPHY_URLS_CACHE_KEY = 'trophy-urls'  # lien du trophée « Ours doré » vers la fiche de sa brasserie (services/members/achievements.py)


def forget(**kwargs):
    """Vide les listes en cache : appelé quand une fiche est ajoutée, modifiée ou supprimée (connect_signals)."""
    cache.delete_many([CACHE_KEY, MARKERS_CACHE_KEY, TROPHY_URLS_CACHE_KEY])


def connect_signals():
    for kind in PLACE_KINDS:
        for signal in (post_save, post_delete):
            signal.connect(forget, sender=kind.model, dispatch_uid=f'forget_places_{kind.key}_{signal is post_save}')


def map_markers():
    """Repères de la carte : {'bar': [...], 'brewery': [...]}, quatre colonnes par fiche (pas les fiches entières), gardés en cache."""
    return cache.get_or_set(MARKERS_CACHE_KEY, _build_markers, CACHE_SECONDS)


def _build_markers():
    return {
        kind.key: list(kind.model.objects.filter(latitude__isnull=False, longitude__isnull=False).order_by('name')
                       .values('slug', 'name', 'latitude', 'longitude')[:MAX_PLACES])
        for kind in PLACE_KINDS
    }


def directory():
    """Liste publique, calculée une fois toutes les 5 minutes puis servie depuis le cache (la liste ne dépend pas du membre)."""
    return cache.get_or_set(CACHE_KEY, _build, CACHE_SECONDS)


def _build():
    places = []
    for kind in PLACE_KINDS:
        geocoded = kind.model.objects.filter(latitude__isnull=False, longitude__isnull=False).order_by('name')
        fields = ('slug', 'name', 'street', 'postal_code', 'city', 'image', 'latitude', 'longitude', 'is_verified')
        places.extend(kind.public(place) for place in geocoded.only(*fields)[:MAX_PLACES])
    return places[:MAX_PLACES]
