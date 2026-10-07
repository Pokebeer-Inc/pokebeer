"""Annuaire des bars et brasseries localisés, pour classer les lieux par distance « Près de moi ».

La position de l'appareil n'est jamais envoyée au serveur : celui-ci publie la liste (données déjà publiques des fiches) et le
navigateur calcule les distances. Pas de position en paramètre, donc rien à journaliser, à conserver ni à protéger côté serveur.
"""
from .places import PLACE_KINDS

MAX_PLACES = 5000  # borne de la taille de la réponse ; au-delà, il faudra découper par zone


def directory():
    places = []
    for kind in PLACE_KINDS:
        geocoded = kind.model.objects.filter(latitude__isnull=False, longitude__isnull=False).order_by('name')
        fields = ('slug', 'name', 'address', 'image', 'latitude', 'longitude', 'is_verified')
        places.extend(kind.public(place) for place in geocoded.only(*fields)[:MAX_PLACES])
    return places[:MAX_PLACES]
