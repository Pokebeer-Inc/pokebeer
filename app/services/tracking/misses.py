"""Demandes sans résultat : ce que les membres cherchent et que le catalogue n'a pas (termes de recherche, codes-barres, étiquettes).

Aucun lien avec un membre : un compteur par source, terme et jour. Un terme est normalisé et borné, et on ne garde ni adresse e-mail ni
suite de chiffres (numéro de téléphone, carte...) qu'un membre aurait tapés dans la recherche par erreur.
"""
import re

from ...domain.text import normalize
from ...models import CatalogMiss
from . import safely
from .counters import increment

Source = CatalogMiss.Source
MIN_LENGTH = 3
MAX_LENGTH = 60
DIGITS = re.compile(r'\d')
SEARCH_SOURCES = {'beers': Source.BEER_SEARCH, 'breweries': Source.BREWERY_SEARCH, 'bars': Source.BAR_SEARCH}


def clean_term(term):
    """Terme conservable (normalisé, espaces réduits), ou None s'il est trop court, trop long ou ressemble à une donnée personnelle."""
    text = ' '.join(normalize(term).split())
    if not MIN_LENGTH <= len(text) <= MAX_LENGTH or '@' in text or len(DIGITS.findall(text)) > len(text) // 2:
        return None
    return text


@safely
def record(source, key=''):
    """Compte une demande sans résultat. `key` : terme recherché (nettoyé ici) ou code-barres ; vide pour une étiquette."""
    if source in SEARCH_SOURCES.values():
        key = clean_term(key)
        if key is None:
            return
    increment(CatalogMiss, {'source': source, 'key': key[:MAX_LENGTH]}, count=1)


def record_search(tab, query):
    """Recherche d'un onglet (beers, breweries, bars) restée sans résultat ; les membres ne sont pas concernés."""
    source = SEARCH_SOURCES.get(tab)
    if source:
        record(source, query)
