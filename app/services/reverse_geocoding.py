"""Géocodage inverse des lieux (OpenStreetMap/Nominatim) avec cache : type de lieu, ville, région, urbain ou rural.

Le service n'est appelé que lorsqu'une position nouvelle apparaît : création d'un lieu ou déplacement de son point
(signaux de `BeerSpot`). Une position déjà en cache ne coûte aucun appel, et une position qui n'est plus utilisée par
aucun lieu est supprimée du cache. La commande `geocode_spots` ne sert qu'à rattraper les lieux antérieurs à cette
fonctionnalité. Seules des coordonnées arrondies à ~11 m sont envoyées, sans information sur le membre.
"""
import logging
import time

import requests
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save, pre_save
from django.utils import timezone

from ..models import BeerSpot, ReverseGeocode

logger = logging.getLogger(__name__)

URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {'User-Agent': 'PokebeerApp/1.0 (analytics)'}
TIMEOUT = 2  # appelé après l'enregistrement d'un lieu, dans la requête du membre : on abandonne vite
REQUEST_DELAY = 1.1  # secondes entre deux appels d'un rattrapage (limite Nominatim : 1 requête/s)
MAX_ATTEMPTS = 3
PRECISION = 10_000

Kind = ReverseGeocode.PlaceKind
HOME_TYPES = {'house', 'residential', 'apartments', 'detached', 'semidetached_house', 'terrace', 'bungalow', 'dormitory', 'farm', 'cabin'}
BAR_TYPES = {'bar', 'pub', 'biergarten', 'cafe', 'restaurant', 'fast_food', 'nightclub', 'food_court'}
OUTDOOR_CATEGORIES = {'natural', 'leisure', 'landuse', 'waterway'}
URBAN_SETTLEMENTS = {'city', 'town'}
SETTLEMENT_KEYS = ('city', 'town', 'village', 'hamlet')


def key_for(lat, lon):
    return round(lat * PRECISION), round(lon * PRECISION)


def classify(payload):
    """Transforme une réponse Nominatim en champs du cache (fonction pure)."""
    category, osm_type = payload.get('category', ''), payload.get('type', '')
    address = payload.get('address') or {}

    if (category, osm_type) in {('craft', 'brewery'), ('industrial', 'brewery'), ('man_made', 'brewery')}:
        kind = Kind.BREWERY
    elif category == 'amenity' and osm_type in BAR_TYPES:
        kind = Kind.BAR
    elif (category == 'building' and osm_type in HOME_TYPES) or (category == 'place' and osm_type == 'house'):
        kind = Kind.HOME
    elif category in OUTDOOR_CATEGORIES:
        kind = Kind.OUTDOOR
    elif category == 'highway':
        kind = Kind.STREET
    else:
        kind = Kind.OTHER

    settlement = next((k for k in SETTLEMENT_KEYS if address.get(k)), '')
    return {
        'place_kind': kind,
        'settlement': settlement,
        'is_urban': settlement in URBAN_SETTLEMENTS if settlement else None,
        'city': ((address.get(settlement) if settlement else address.get('municipality')) or '')[:150],
        'postcode': (address.get('postcode') or '')[:20],
        'department': (address.get('county') or address.get('state_district') or '')[:150],
        'region': (address.get('state') or '')[:150],
        'country_code': (address.get('country_code') or '')[:2].lower(),
        'osm_category': category[:50],
        'osm_type': osm_type[:50],
    }


def fetch_payload(lat, lon):
    response = requests.get(
        URL, headers=HEADERS, timeout=TIMEOUT,
        params={'lat': f'{lat:.4f}', 'lon': f'{lon:.4f}', 'format': 'jsonv2', 'zoom': 18, 'addressdetails': 1, 'accept-language': 'fr'},
    )
    response.raise_for_status()
    payload = response.json()
    if 'error' in payload:
        raise ValueError(payload['error'])
    return payload


def resolve_position(key, fetch=None):
    """Résout une position si elle ne l'est pas déjà (un cache plein ne coûte aucun appel). Renvoie True si elle est résolue."""
    row, _ = ReverseGeocode.objects.get_or_create(lat_e4=key[0], lon_e4=key[1])
    if row.is_resolved:
        return True
    fetch = fetch or fetch_payload  # résolu à l'appel : substituable dans les tests
    now = timezone.now()
    try:
        fields = classify(fetch(key[0] / PRECISION, key[1] / PRECISION))
    except Exception as error:  # réseau, quota, adresse inconnue : jamais bloquant pour l'appelant
        logger.warning("Géocodage inverse impossible pour %s : %s", key, error)
        ReverseGeocode.objects.filter(pk=row.pk).update(failed_attempts=row.failed_attempts + 1, last_attempt_at=now)
        return False
    ReverseGeocode.objects.filter(pk=row.pk).update(**fields, resolved_at=now, last_attempt_at=now)
    return True


def prune_if_unused(key):
    """Oublie une position que plus aucun lieu n'utilise : on ne garde pas l'emplacement d'un lieu supprimé ou déplacé."""
    half = 0.5 / PRECISION
    nearby = BeerSpot.objects.filter(
        latitude__gte=key[0] / PRECISION - half, latitude__lt=key[0] / PRECISION + half,
        longitude__gte=key[1] / PRECISION - half, longitude__lt=key[1] / PRECISION + half,
    ).values_list('latitude', 'longitude')
    if not any(key_for(lat, lon) == key for lat, lon in nearby):
        ReverseGeocode.objects.filter(lat_e4=key[0], lon_e4=key[1]).delete()


# --- Déclencheurs : uniquement quand la position d'un lieu apparaît ou change ---

POSITION_BEFORE_ATTR = '_geocoded_position_before'


def _remember_previous_position(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        return
    previous = sender.objects.filter(pk=instance.pk).values_list('latitude', 'longitude').first()
    if previous:
        setattr(instance, POSITION_BEFORE_ATTR, key_for(*previous))


def _on_spot_saved(sender, instance, created=False, raw=False, **kwargs):
    before = instance.__dict__.pop(POSITION_BEFORE_ATTR, None)
    if raw:
        return
    current = key_for(instance.latitude, instance.longitude)
    if not created and before == current:
        return  # une modification sans déplacement ne coûte rien
    transaction.on_commit(lambda: resolve_position(current))
    if before is not None and before != current:
        transaction.on_commit(lambda: prune_if_unused(before))


def _on_spot_deleted(sender, instance, **kwargs):
    key = key_for(instance.latitude, instance.longitude)
    transaction.on_commit(lambda: prune_if_unused(key))


def connect_signals():
    pre_save.connect(_remember_previous_position, sender=BeerSpot, weak=False, dispatch_uid='geocode_spot_pre')
    post_save.connect(_on_spot_saved, sender=BeerSpot, weak=False, dispatch_uid='geocode_spot_post')
    post_delete.connect(_on_spot_deleted, sender=BeerSpot, weak=False, dispatch_uid='geocode_spot_del')


# --- Rattrapage manuel des lieux antérieurs (commande geocode_spots) ---

def pending_keys():
    """Positions de lieux à résoudre : jamais tentées, ou en échec mais sous le nombre maximal d'essais."""
    wanted = {key_for(lat, lon) for lat, lon in BeerSpot.objects.values_list('latitude', 'longitude')}
    done = set(ReverseGeocode.objects.filter(Q(resolved_at__isnull=False) | Q(failed_attempts__gte=MAX_ATTEMPTS))
               .values_list('lat_e4', 'lon_e4'))
    return sorted(wanted - done)


def resolve_pending(limit=100, fetch=None, sleep=time.sleep):
    """Rattrapage : résout au plus `limit` positions en respectant la limite d'1 requête/s."""
    stats = {'resolved': 0, 'failed': 0}
    for index, key in enumerate(pending_keys()[:limit]):
        if index:
            sleep(REQUEST_DELAY)
        stats['resolved' if resolve_position(key, fetch) else 'failed'] += 1
    return stats
