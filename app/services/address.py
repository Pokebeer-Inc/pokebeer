"""Adresse postale d'un établissement : découpage en rue, code postal et ville, et recomposition.

Pures fonctions : elles servent aux modèles (propriété `address`), à la migration qui découpe les adresses existantes et aux formulaires.
"""
import re

POSTAL_CODE = re.compile(r'[0-9]{5}')  # code postal français, chiffres ASCII seulement (les établissements sont référencés par SIRET)
_TAIL = re.compile(r'^(?P<street>.*?)[,\s]*\b(?P<postal>[0-9]{5})\s+(?P<city>[^,0-9][^,]*?)\s*(?:,\s*France)?\s*$', re.IGNORECASE | re.DOTALL)


def parse(full):
    """(rue, code postal, ville) d'une adresse écrite d'un seul tenant ; sans code postal reconnu, tout est la rue."""
    text = ' '.join((full or '').split())
    match = _TAIL.match(text)
    if not match:
        return text, '', ''
    return match.group('street').strip(' ,'), match.group('postal'), match.group('city').strip()


def compose(street, postal_code, city):
    """« 5 Rue du Port, 29900 Concarneau » (les parties absentes sont simplement omises)."""
    locality = ' '.join(part for part in (postal_code, city) if part)
    return ', '.join(part for part in (street, locality) if part)
