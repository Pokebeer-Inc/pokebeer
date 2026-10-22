"""Itinéraire vers un bar ou une brasserie : liens Google Maps et Plans (Apple), construits côté serveur.

Les adresses de départ ne sont jamais envoyées : l'application ne connaît pas la position du membre, c'est l'application de cartes
qui s'en charge. Tout ce qui entre dans une adresse web est encodé (`urlencode`) ; l'hôte, lui, est une constante.
"""
from urllib.parse import urlencode

GOOGLE_MAPS = 'https://www.google.com/maps/dir/?'
APPLE_MAPS = 'https://maps.apple.com/?'


def _destination(place):
    """Ce qu'on donne aux cartes : le nom et l'adresse (la carte reconnaît l'établissement), sinon ses coordonnées ; None si rien."""
    if place.address:
        return f'{place.name}, {place.address}'
    if place.latitude is not None and place.longitude is not None:
        return f'{place.latitude:.6f},{place.longitude:.6f}'
    return None


def links(place):
    """{'google': url, 'apple': url} pour aller à l'établissement, ou None s'il n'a ni adresse ni coordonnées."""
    destination = _destination(place)
    if destination is None:
        return None
    return {
        'google': GOOGLE_MAPS + urlencode({'api': 1, 'destination': destination}),
        'apple': APPLE_MAPS + urlencode({'daddr': destination, 'dirflg': 'd'}),
    }
