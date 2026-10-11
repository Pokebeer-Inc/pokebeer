"""Du nom d'un lieu (« Dublin », « Lille centre ») à ses coordonnées, via Nominatim (OpenStreetMap, gratuit)."""
import logging

from django.core.cache import cache

from ...establishments import nominatim
from ...common import upstream
from .geo import Coordinates
from .sanitize import clean_text

logger = logging.getLogger(__name__)

CACHE_SECONDS = 7 * 24 * 3600
MAX_QUERY_LENGTH = 80


def geocode(place_name):
    """Coordonnées du lieu nommé, ou None s'il est introuvable ou si le service est indisponible."""
    query = clean_text(place_name, MAX_QUERY_LENGTH)
    if not query:
        return None
    cache_key = f'chat-geocode:{query.lower()}'
    cached = cache.get(cache_key)
    if cached is not None:
        return Coordinates.parse(cached) if cached else None
    try:
        first = nominatim.search(query)
    except upstream.UpstreamUnavailable:
        return None
    coordinates = Coordinates.parse({'lat': first.get('lat'), 'lng': first.get('lon')}) if first else None
    cache.set(cache_key, {'lat': coordinates.lat, 'lng': coordinates.lng} if coordinates else '', CACHE_SECONDS)
    return coordinates
