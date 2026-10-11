"""Nominatim (OpenStreetMap) : le seul endroit qui l'interroge, pour la recherche d'une adresse et pour le géocodage inverse.

Les appels passent par `upstream` : même identification de l'application (User-Agent exigé par Nominatim), aucune redirection suivie, taille
de réponse bornée, réponse validée. Le délai est choisi par l'appelant (court dans une requête web, plus patient pour un rattrapage).
"""
from django.conf import settings

from ..common import upstream


def search(query, timeout=None):
    """Premier résultat {'lat': ..., 'lon': ...} pour cette adresse ou ce nom de lieu, ou None s'il n'y en a pas.

    Lève upstream.UpstreamUnavailable si le service ne répond pas correctement."""
    results = upstream.get_json(settings.NOMINATIM_URL, params={'q': query, 'format': 'json', 'limit': 1}, timeout=timeout)
    first = results[0] if isinstance(results, list) and results else None
    return first if isinstance(first, dict) else None


def reverse(lat, lon, timeout=None):
    """Détails du lieu situé à ces coordonnées (réponse de Nominatim, 'jsonv2' avec adresse, en français).

    Lève upstream.UpstreamUnavailable si le service ne répond pas, ValueError s'il ne connaît pas ce point."""
    payload = upstream.get_json(
        settings.NOMINATIM_REVERSE_URL, timeout=timeout,
        params={'lat': f'{lat:.4f}', 'lon': f'{lon:.4f}', 'format': 'jsonv2', 'zoom': 18, 'addressdetails': 1, 'accept-language': 'fr'},
    )
    if not isinstance(payload, dict):
        raise ValueError("Position inconnue de Nominatim")
    if 'error' in payload:
        raise ValueError(payload['error'])
    return payload
