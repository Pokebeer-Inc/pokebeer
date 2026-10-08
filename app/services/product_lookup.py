"""Recherche d'une bière par son code-barres dans Open Food Facts (base de produits collaborative, accès libre).

Seul un code EAN valide (chiffres uniquement, voir ean.normalize) est inséré dans l'adresse. La réponse est une donnée non fiable :
l'appel passe par services/upstream.py (hôte fixe, taille bornée, sans redirection) et les champs sont réduits et nettoyés par beer_fields.
"""
from . import beer_fields, upstream

URL = 'https://world.openfoodfacts.org/api/v2/product/{ean}.json'
FIELDS = 'product_name,brands,categories_tags,nutriments'
LookupUnavailable = upstream.UpstreamUnavailable  # nom historique : une panne de la base de produits


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
    data = upstream.get_json(URL.format(ean=ean), {'fields': FIELDS})
    product = data.get('product') if isinstance(data, dict) and data.get('status') == 1 else None
    if not isinstance(product, dict) or not _is_beer(product):
        return None
    beer = beer_fields.clean({
        'name': product.get('product_name'), 'brewery': _first_brand(product.get('brands')), 'degree': _alcohol(product.get('nutriments')),
    })
    return beer if beer['name'] else None
