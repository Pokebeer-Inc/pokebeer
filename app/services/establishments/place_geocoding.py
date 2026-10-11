"""Coordonnées des brasseries et des bars : calculées à partir de leur adresse (Nominatim) quand elle change.

Branché sur le signal pre_save (voir apps.py), pour que les coordonnées soient enregistrées dans la même écriture que l'adresse.
Le géocodage est synchrone dans la requête web : délai court (connexion + lecture) ; en cas d'échec la fiche est enregistrée sans coordonnées.
"""
import logging

from django.db.models.signals import pre_save

from ...models import Bar, Brewery
from .nominatim import search as search_address

logger = logging.getLogger(__name__)

GEOCODING_TIMEOUT = 2


def locate(place):
    """(latitude, longitude) de l'adresse de la fiche, ou (None, None). Sans rue, la fiche n'est pas placée : un point au centre de la ville
    laisserait croire à l'adresse de l'établissement."""
    if not place.street:
        return None, None
    try:
        found = search_address(place.address, timeout=GEOCODING_TIMEOUT)
        if found:
            return float(found['lat']), float(found['lon'])
    except Exception as error:
        # En cas de coupure réseau ou erreur API, on ne fait pas crasher l'enregistrement
        logger.warning("Géocodage impossible : %s", type(error).__name__)
    # Adresse introuvable ou service indisponible : mieux vaut pas de carte que les coordonnées de l'ancienne adresse
    return None, None


def _geocode_before_save(sender, instance, **kwargs):
    if instance.address_changed():  # l'API n'est appelée QUE si l'adresse a changé
        instance.latitude, instance.longitude = locate(instance)


def connect_signals():
    for model in (Brewery, Bar):
        pre_save.connect(_geocode_before_save, sender=model, dispatch_uid=f'geocode_{model.__name__}')
