"""Recherche d'une bière par son code-barres dans Open Food Facts (base de produits collaborative, accès libre).

Seul un code EAN valide (chiffres uniquement, voir ean.normalize) est inséré dans l'adresse, qui part toujours vers le même hôte :
rien de ce que l'utilisateur tape ne choisit la destination. La réponse est une donnée non fiable : taille bornée, aucune
redirection suivie, champs réduits et nettoyés par beer_fields. Aucune donnée du membre n'est transmise : la requête vient du serveur.
"""
import json
import logging

import requests
from django.conf import settings

from . import beer_fields

logger = logging.getLogger(__name__)

URL = 'https://world.openfoodfacts.org/api/v2/product/{ean}.json'
FIELDS = 'product_name,brands,categories_tags,nutriments'
MAX_RESPONSE_BYTES = 256 * 1024


class LookupUnavailable(Exception):
    """La base de produits ne répond pas correctement (panne, délai, réponse invalide) : à distinguer d'un code inconnu."""


def _read_limited(response):
    body = response.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)
    if len(body) > MAX_RESPONSE_BYTES:
        raise LookupUnavailable("Réponse trop volumineuse")
    return body


def _alcohol(nutriments):
    for key in ('alcohol_100g', 'alcohol_value', 'alcohol'):
        if isinstance(nutriments, dict) and nutriments.get(key) is not None:
            return nutriments[key]
    return None


def _is_beer(product):
    tags = product.get('categories_tags')
    return isinstance(tags, list) and any(isinstance(tag, str) and 'beer' in tag for tag in tags)


def _first_brand(brands):
    return brands.split(',')[0] if isinstance(brands, str) else None


def fetch(ean):
    """Bière correspondant à `ean` ({name, brewery, style, degree, bitterness}), ou None si le code est inconnu ou n'est pas une bière.

    Lève LookupUnavailable si la base ne répond pas correctement.
    """
    try:
        response = requests.get(
            URL.format(ean=ean), params={'fields': FIELDS}, headers={'User-Agent': settings.OPEN_FOOD_FACTS_USER_AGENT},
            timeout=settings.OPEN_FOOD_FACTS_TIMEOUT, allow_redirects=False, stream=True,
        )
    except requests.RequestException as error:
        logger.warning("Open Food Facts injoignable : %s", type(error).__name__)
        raise LookupUnavailable from error
    with response:
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise LookupUnavailable(f"Statut {response.status_code}")
        try:
            data = json.loads(_read_limited(response))
        except (ValueError, requests.RequestException) as error:
            raise LookupUnavailable("Réponse illisible") from error
    product = data.get('product') if isinstance(data, dict) and data.get('status') == 1 else None
    if not isinstance(product, dict) or not _is_beer(product):
        return None
    beer = beer_fields.clean({
        'name': product.get('product_name'), 'brewery': _first_brand(product.get('brands')), 'degree': _alcohol(product.get('nutriments')),
    })
    return beer if beer['name'] else None
