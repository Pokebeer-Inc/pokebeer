"""Bars et brasseries proches d'une position, depuis des sources gratuites : la base Pokebeer, puis OpenStreetMap.

Chaque source répond à la même question (`search`) ; en ajouter une (autre annuaire libre, avis) ne modifie ni l'outil du modèle ni le
classement. Les textes venus de l'extérieur sont nettoyés ici, avant de pouvoir atteindre le modèle.
"""
import hashlib
import logging
import math
import re
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from .. import match_keys, upstream
from ..places import BAR, BREWERY, PLACE_KINDS
from .geo import Coordinates
from .sanitize import clean_text

logger = logging.getLogger(__name__)

MAX_RESULTS = 8
MAX_RADIUS_KM = 25
DEFAULT_RADIUS_KM = 3  # Overpass est un service public partagé : une zone réduite répond plus vite et tronque moins
SAME_PLACE_KM = 0.15  # deux fiches de même nature à moins de 150 m et de nom proche sont le même lieu
SAME_NAME_SIMILARITY = 0.6
OVERPASS_TIMEOUT_SECONDS = 7
OVERPASS_LIMIT = 80
CACHE_SECONDS = 3600
NAME_LENGTH = 80
KEYWORD_LENGTH = 30
_KEYWORD_CHARACTERS = re.compile(r"[^\w\s'-]", re.UNICODE)


@dataclass(frozen=True)
class Place:
    name: str
    kind: str  # 'bar' | 'brewery'
    distance_km: float
    address: str
    link: str  # chemin relatif Pokebeer ou carte OpenStreetMap : les seuls liens que la réponse peut contenir
    source: str  # 'pokebeer' | 'openstreetmap'
    verified: bool = False
    keyword_match: bool = False


def clean_keyword(keyword):
    """Mot-clé réduit à des lettres, chiffres, espaces, tirets et apostrophes : il est ensuite inséré entre guillemets dans la requête
    Overpass, aucun autre caractère ne peut donc en sortir."""
    return _KEYWORD_CHARACTERS.sub('', clean_text(keyword, KEYWORD_LENGTH)).strip()


def _mentions(keyword, *texts):
    return bool(keyword) and any(keyword.lower() in (text or '').lower() for text in texts)


class PokebeerSource:
    """Fiches de la base (déjà publiques sur le site), les vérifiées étant remontées par le classement."""

    def search(self, origin, radius_km, kind, keyword):
        lat_min, lat_max, lng_min, lng_max = origin.bounding_box(radius_km)
        places = []
        for place_kind in PLACE_KINDS:
            if kind not in (place_kind.key, 'any'):
                continue
            nearby = place_kind.model.objects.filter(latitude__range=(lat_min, lat_max), longitude__range=(lng_min, lng_max))
            for place in nearby.only('slug', 'name', 'description', 'street', 'postal_code', 'city', 'latitude', 'longitude', 'is_verified')[:200]:
                distance = origin.distance_km(place.latitude, place.longitude)
                if distance <= radius_km:
                    places.append(Place(
                        name=clean_text(place.name, NAME_LENGTH), kind=place_kind.key, distance_km=distance,
                        address=clean_text(place.address, 120), link=place_kind.map_path(place), source='pokebeer',
                        verified=place.is_verified, keyword_match=_mentions(keyword, place.name, place.description),
                    ))
        return places


class OpenStreetMapSource:
    """Pubs, bars et brasseries d'OpenStreetMap (Overpass). Une mention du mot-clé dans les étiquettes de la fiche vaut confirmation."""

    SELECTORS = {
        BAR.key: ('["amenity"~"^(pub|bar|biergarten)$"]',),
        BREWERY.key: ('["craft"="brewery"]', '["microbrewery"="yes"]'),
    }
    def search(self, origin, radius_km, kind, keyword):
        selectors = [s for key, group in self.SELECTORS.items() if kind in (key, 'any') for s in group]
        elements = self._fetch(origin, radius_km, selectors)
        return [place for place in (self._to_place(element, origin, keyword) for element in elements) if place]

    @staticmethod
    def _fetch(origin, radius_km, selectors):
        around = f'(around:{int(radius_km * 1000)},{origin.lat:.2f},{origin.lng:.2f})'
        query = f'[out:json][timeout:{OVERPASS_TIMEOUT_SECONDS}];(' + ''.join(f'nwr{s}{around};' for s in selectors) + f');out center tags {OVERPASS_LIMIT};'
        cache_key = 'chat-overpass:' + hashlib.sha256(query.encode()).hexdigest()
        elements = cache.get(cache_key)
        if elements is None:
            data = upstream.get_json(settings.OVERPASS_URL, params={'data': query}, timeout=OVERPASS_TIMEOUT_SECONDS + 1)
            elements = data.get('elements', []) if isinstance(data, dict) else []
            cache.set(cache_key, elements, CACHE_SECONDS)
        return elements

    @staticmethod
    def _to_place(element, origin, keyword):
        # La réponse d'un service extérieur n'est pas crue : tout élément mal formé est simplement ignoré
        if not isinstance(element, dict) or not isinstance(element.get('tags'), dict):
            return None
        tags = element['tags']
        point = element.get('center') or element
        try:
            lat, lng = float(point['lat']), float(point['lon'])
        except (KeyError, TypeError, ValueError):
            return None
        name = clean_text(tags.get('name'), NAME_LENGTH)
        if not name or not (math.isfinite(lat) and math.isfinite(lng)):
            return None
        is_brewery = tags.get('craft') == 'brewery' or tags.get('microbrewery') == 'yes'
        # Bière servie : étiquette « brewery » (liste de marques), « drink:* » ou description de la fiche
        served = [tags.get('brewery'), tags.get('description')] + [key for key, value in tags.items() if key.startswith('drink:') and value == 'yes']
        street = ' '.join(filter(None, (tags.get('addr:housenumber'), tags.get('addr:street'))))
        address = ', '.join(filter(None, (clean_text(street, 80), clean_text(tags.get('addr:city'), 50))))
        return Place(
            name=name, kind=BREWERY.key if is_brewery else BAR.key, distance_km=origin.distance_km(lat, lng), address=address,
            link=f'https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lng:.5f}#map=18/{lat:.5f}/{lng:.5f}', source='openstreetmap',
            keyword_match=_mentions(keyword, name, *served),
        )


def _is_duplicate(candidate, existing):
    return (
        candidate.kind == existing.kind
        and abs(candidate.distance_km - existing.distance_km) <= SAME_PLACE_KM
        and match_keys.similarity(match_keys.tokens(candidate.name), match_keys.tokens(existing.name)) >= SAME_NAME_SIMILARITY
    )


@dataclass(frozen=True)
class NearbyResult:
    places: list
    complete: bool  # False si une source n'a pas répondu : la liste peut être incomplète


def find_nearby(origin, kind='any', keyword='', radius_km=DEFAULT_RADIUS_KM, sources=None):
    """Lieux proches classés : ceux qui mentionnent le mot-clé, puis les fiches vérifiées, puis la distance. La base Pokebeer prime
    sur OpenStreetMap quand les deux décrivent le même lieu."""
    radius_km = min(max(radius_km, 1), MAX_RADIUS_KM)
    keyword = clean_keyword(keyword)
    complete, found = True, []
    for source in sources or (PokebeerSource(), OpenStreetMapSource()):
        try:
            candidates = source.search(origin, radius_km, kind, keyword)
        except upstream.UpstreamUnavailable:
            complete = False
            continue
        for candidate in candidates:
            if not any(_is_duplicate(candidate, known) for known in found):
                found.append(candidate)
    found.sort(key=lambda place: (not place.keyword_match, not place.verified, place.distance_km))
    return NearbyResult(found[:MAX_RESULTS], complete)
