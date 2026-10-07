"""Champs d'une bière reçus d'une source extérieure (IA, base de produits) : réduits aux champs connus, convertis et bornés.

Ces valeurs sont des données non fiables qui remplissent un formulaire : texte court sans balise, sans emoji ni caractère de
contrôle ; degré de 0 à 100 ; amertume de 0 à 500 ; tout le reste est ignoré.
"""
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TEXT_LIMITS = {'name': 150, 'brewery': 150, 'style': 100}
MAX_DEGREE, MAX_BITTERNESS = 100, 500
FIELDS = ('name', 'brewery', 'style', 'degree', 'bitterness')
_UNWANTED = {'So', 'Cc', 'Cf', 'Cs', 'Co', 'Cn'}  # symboles et emoji, contrôle, format (invisibles), non attribués


def clean_text(value, limit):
    if not isinstance(value, str):
        return None
    visible = ''.join(char for char in value if unicodedata.category(char) not in _UNWANTED or char.isspace())
    cleaned = re.sub(r'[<>]', '', ' '.join(visible.split()))  # un espace, jamais de balise
    return cleaned[:limit].strip() or None


def clean_number(value, maximum, decimals):
    """Nombre décimal arrondi à 0,1 (decimals=True) ou entier ; None s'il est absent, invalide ou hors bornes."""
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).replace(',', '.').strip())
    except InvalidOperation:
        return None
    if not number.is_finite() or not 0 <= number <= maximum:
        return None
    return float(number.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)) if decimals else int(number)


def clean(data):
    """Les cinq champs d'une bière, nettoyés, à partir d'un dict quelconque."""
    cleaned = {key: clean_text(data.get(key), limit) for key, limit in TEXT_LIMITS.items()}
    cleaned['degree'] = clean_number(data.get('degree'), MAX_DEGREE, decimals=True)
    cleaned['bitterness'] = clean_number(data.get('bitterness'), MAX_BITTERNESS, decimals=False)
    return cleaned
