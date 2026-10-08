"""Clés de comparaison des noms de bières et de brasseries : ce qui reste d'un nom quand on enlève ce qui ne l'identifie pas.

Fonctions pures, sans base de données : elles servent aux modèles (clés enregistrées), à la migration et au service de détection.

- clé stricte (`strict_key`) : minuscules, sans accents ni ponctuation (« I.P.A » = « ipa »), sans articles ni formes juridiques,
  sans quantités (« 33cl », « 5,6% ») pour une bière ; mots triés (l'ordre ne compte pas).
- clé large (`loose_key`) : pour une brasserie ou un bar, la clé stricte sans les mots génériques (brasserie, microbrasserie, brewery, bar,
  pub...) : « Microbrasserie du Coin » et « Brasserie du Coin » ont la même clé large, pas la même clé stricte. Pour une bière, identique.
Les chiffres identifient (« Houblon 1 » n'est pas « Houblon 2 ») : ils ne sont jamais effacés, et deux noms qui diffèrent par eux
ne sont jamais jugés proches (voir similarity).
"""
import re
from difflib import SequenceMatcher

from . import search

BEER, BREWERY, BAR = 'beer', 'brewery', 'bar'
MAX_NAME_LENGTH = 150
KEY_LENGTH = 200

ARTICLES = frozenset({
    'le', 'la', 'les', 'l', 'un', 'une', 'du', 'de', 'des', 'd', 'et', 'au', 'aux', 'and', 'the', 'of', 'der', 'die', 'das', 'el', 'los', 'las', 'del', 'y',
})
LEGAL_FORMS = frozenset({'sas', 'sarl', 'sa', 'eurl', 'sasu', 'snc', 'ltd', 'llc', 'inc', 'gmbh', 'co', 'cie', 'company'})
BREWERY_WORDS = frozenset({
    'brasserie', 'brasseries', 'microbrasserie', 'microbrasseries', 'micro', 'brewery', 'breweries', 'brewing', 'brewhouse', 'brewers',
    'brewer', 'brasseur', 'brasseurs', 'brauerei', 'cerveceria', 'cervecera', 'atelier', 'artisanale', 'artisanal',
})
BAR_WORDS = frozenset({
    'bar', 'bars', 'pub', 'taverne', 'cafe', 'bistro', 'bistrot', 'brasserie', 'restaurant', 'brewpub', 'taproom', 'caviste', 'cave', 'biere', 'bieres', 'beer',
})
BEER_WORDS = frozenset({'biere', 'bieres', 'beer', 'beers', 'bier', 'cerveza'})

PROBABLE_SIMILARITY = 0.8   # au-dessus, deux noms sont jugés proches
MIN_LENGTH_FOR_RATIO = 6    # en dessous, un écart d'une lettre change trop le sens (« brune » / « brume ») : seule l'égalité compte

_QUANTITY = re.compile(r'\d+(?:[.,]\d+)?\s*%|\b\d+(?:[.,]\d+)?\s*(?:cl|ml|litres?|l|deg|vol)\b')
_NON_ALPHANUMERIC = re.compile(r'[^a-z0-9]+')


def _merge_initials(tokens):
    """« i p a » (issu de « I.P.A. ») devient « ipa » : une suite d'au moins deux lettres isolées est recollée."""
    merged, run = [], []
    for token in tokens + ['']:
        if len(token) == 1 and token.isalpha():
            run.append(token)
            continue
        if len(run) >= 2:
            merged.append(''.join(run))
        else:
            merged.extend(run)
        run = []
        if token:
            merged.append(token)
    return merged


def tokens(text, kind=BEER):
    """Mots d'un nom, normalisés (quantités retirées pour une bière), avant tout filtrage de mots génériques."""
    normalized = search.normalize((text or '')[:MAX_NAME_LENGTH])
    if kind == BEER:
        normalized = _QUANTITY.sub(' ', normalized)
    return _merge_initials(_NON_ALPHANUMERIC.sub(' ', normalized).split())


def strict_tokens(text, kind=BEER):
    words = tokens(text, kind)
    dropped = ARTICLES | LEGAL_FORMS | (BEER_WORDS if kind == BEER else frozenset())
    kept = [word for word in words if word not in dropped]
    return sorted(set(kept or words))  # un nom qui ne serait que des mots génériques garde ses mots


def loose_tokens(text, kind=BEER):
    strict = strict_tokens(text, kind)
    generic = {BREWERY: BREWERY_WORDS, BAR: BAR_WORDS}.get(kind)
    if generic:
        return [word for word in strict if word not in generic] or strict
    return strict


def strict_key(text, kind=BEER):
    return ' '.join(strict_tokens(text, kind))[:KEY_LENGTH]


def loose_key(text, kind=BEER):
    return ' '.join(loose_tokens(text, kind))[:KEY_LENGTH]


def similarity(first, second):
    """Proximité (0 à 1) de deux listes de mots : 1 si identiques, 0 si leurs chiffres diffèrent, sinon le meilleur de la part de mots
    communs et de la ressemblance des textes (fautes de frappe, lettre en trop). Courts : seule l'égalité compte."""
    if first == second:
        return 1.0
    if {word for word in first if word.isdigit()} != {word for word in second if word.isdigit()}:
        return 0.0
    left, right = set(first), set(second)
    shared = len(left & right) / len(left | right)
    a, b = ' '.join(first), ' '.join(second)
    ratio = SequenceMatcher(None, a, b).ratio() if min(len(a), len(b)) >= MIN_LENGTH_FOR_RATIO else 0.0
    return max(shared, ratio)


def without(words, other_words):
    """`words` privé de ceux de `other_words` (ex. le nom de la brasserie recopié dans le nom de la bière), sauf s'il ne resterait rien."""
    remaining = [word for word in words if word not in set(other_words)]
    return remaining or list(words)
