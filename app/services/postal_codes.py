"""Code postal -> commune(s), pour que la ville d'un établissement vienne du code postal et non d'une saisie libre.

L'annuaire officiel des communes (geo.api.gouv.fr, sans clé) donne les communes d'un code postal ; la réponse est mémorisée en base
(table PostalCode) : une seconde saisie du même code ne refait aucun appel. Un code postal peut couvrir plusieurs communes : le membre
choisit alors la sienne. Si l'annuaire est indisponible, la saisie n'est pas bloquée (la ville reste à compléter plus tard).
"""
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..models import PostalCode
from . import beer_fields, search, upstream
from .address import POSTAL_CODE

URL = 'https://geo.api.gouv.fr/communes'
MAX_AGE = timedelta(days=90)
MAX_COMMUNES = 50


class PostalCodeError(ValueError):
    """Code postal ou ville refusé : le message est affichable tel quel, `field` désigne le champ du formulaire concerné."""

    def __init__(self, message, field='postal_code'):
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class Resolution:
    postal_code: str
    city: str            # nom officiel de la commune ; vide si l'annuaire était indisponible et que rien n'a été saisi
    verified: bool       # la ville a été confirmée par l'annuaire


def is_valid_format(code):
    return isinstance(code, str) and POSTAL_CODE.fullmatch(code) is not None


def _fetch(code):
    data = upstream.get_json(URL, {'codePostal': code, 'fields': 'nom', 'format': 'json'})
    if not isinstance(data, list):
        return []
    names = (beer_fields.clean_text(item.get('nom'), 100) for item in data[:MAX_COMMUNES] if isinstance(item, dict))
    return sorted({name for name in names if name}, key=search.normalize)


def communes(code):
    """Noms des communes du code postal (liste vide : code inconnu). Lève upstream.UpstreamUnavailable si l'annuaire ne répond pas
    et que rien n'est mémorisé."""
    if not is_valid_format(code):
        return []
    rows = list(PostalCode.objects.filter(code=code))
    if rows and timezone.now() - max(row.fetched_at for row in rows) < MAX_AGE:
        return sorted((row.city for row in rows if row.city), key=search.normalize)
    names = _fetch(code)
    with transaction.atomic():
        PostalCode.objects.filter(code=code).delete()
        PostalCode.objects.bulk_create([PostalCode(code=code, city=name) for name in names] or [PostalCode(code=code, city='')])
    return names


def resolve(code, typed_city=''):
    """Code postal et commune confirmés. `typed_city` : la commune choisie ou saisie (obligatoire si le code en couvre plusieurs).

    Lève PostalCodeError (code mal formé ou inconnu, ville qui n'en fait pas partie, choix à faire).
    """
    code = (code or '').strip()
    typed_city = ' '.join((typed_city or '').split())[:100]
    if not code:
        if typed_city:
            raise PostalCodeError("Indiquez le code postal : la ville en découle.")
        return Resolution('', '', False)
    if not is_valid_format(code):
        raise PostalCodeError("Le code postal doit comporter 5 chiffres.")
    try:
        names = communes(code)
    except upstream.UpstreamUnavailable:
        # Annuaire indisponible : on garde le code postal, la ville sera complétée plus tard
        return Resolution(code, typed_city, False)
    if not names:
        raise PostalCodeError("Ce code postal est inconnu.")
    if typed_city:
        match = next((name for name in names if search.normalize(name) == search.normalize(typed_city)), None)
        if match is None:
            raise PostalCodeError(f"Cette ville ne correspond pas au code postal {code} : {', '.join(names)}.", field='city')
        return Resolution(code, match, True)
    if len(names) == 1:
        return Resolution(code, names[0], True)
    raise PostalCodeError(f"Ce code postal couvre plusieurs communes, choisissez la vôtre : {', '.join(names)}.", field='city')
