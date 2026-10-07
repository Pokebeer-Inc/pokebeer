"""Recherche unique : bières, brasseries, bars et membres.

- Insensible à la casse et aux accents : la colonne et le terme passent par `f_unaccent(lower(...))`, la même expression que les
  index trigramme de la migration 0070 ; PostgreSQL les utilise donc au lieu de parcourir toute la table.
- Plusieurs mots : chacun doit se retrouver quelque part (« ipa brasserie du coin » trouve une IPA de cette brasserie).
- Tolérance aux fautes de frappe pour les mots d'au moins quatre lettres (alphabétiques) (similarité de mot, opérateur trigramme indexé).
- Pertinence : nom exact, puis nom commençant par la recherche, puis mot du nom, puis le reste.
Chaque fonction affine un queryset déjà restreint par l'appelant (droits, blocages) : ce module ne décide pas de la visibilité.
"""
import unicodedata

from django.db.models import Case, F, Func, IntegerField, Q, TextField, Value, When
from django.db.models.functions import Lower

MAX_TERMS = 5
MAX_QUERY_LENGTH = 100
FUZZY_MIN_LENGTH = 4
LIGATURES = str.maketrans({'œ': 'oe', 'æ': 'ae', 'ß': 'ss'})  # absentes des règles de décomposition Unicode
RANK_FIELD = 'search_rank'


def normalize(text):
    """Minuscules sans accents, comme f_unaccent(lower(...)) côté base."""
    decomposed = unicodedata.normalize('NFKD', (text or '').lower().translate(LIGATURES))
    return ''.join(char for char in decomposed if not unicodedata.combining(char)).strip()


def terms(query):
    """Mots de la recherche, normalisés, dédoublonnés et bornés (une saisie géante ne doit pas fabriquer une requête géante)."""
    words = normalize((query or '')[:MAX_QUERY_LENGTH]).split()
    return list(dict.fromkeys(words))[:MAX_TERMS]


def indexed(column):
    """Expression des index trigramme : f_unaccent(lower(colonne))."""
    return Func(Lower(column), function='f_unaccent', output_field=TextField())


def _matches(word, columns):
    condition = Q()
    for name in columns:
        condition |= Q(**{f'{name}__contains': word})
        if len(word) >= FUZZY_MIN_LENGTH and word.isalpha():  # ni chiffres ni symboles : « 100% » ne ressemble pas à « 100 »
            condition |= Q(**{f'{name}__trigram_word_similar': word})
    return condition


def _rank(name_alias, words):
    """0 nom exact, 1 nom qui commence par la recherche, 2 un mot du nom commence par le premier mot, 3 le reste."""
    whole = ' '.join(words)
    return Case(
        When(**{name_alias: whole}, then=Value(0)),
        When(**{f'{name_alias}__startswith': words[0]}, then=Value(1)),
        When(**{f'{name_alias}__contains': ' ' + words[0]}, then=Value(2)),
        default=Value(3), output_field=IntegerField(),
    )


def search(queryset, query, name, *other_columns, related=()):
    """Affine `queryset` selon `query` (inchangé sans recherche). `name` : colonne du nom, aussi utilisée pour la pertinence ;
    `other_columns` : autres colonnes de la table ; `related` : triplets (clé étrangère, modèle lié, colonne) pour chercher aussi
    dans une table liée (ex. le nom de la brasserie d'une bière).

    Une table liée est interrogée par sous-requête (`fk IN (SELECT ...)`) et non par jointure : un OU entre deux tables empêcherait
    PostgreSQL d'utiliser les index trigramme, alors que chaque sous-requête a le sien.

    Le queryset renvoyé porte l'annotation `search_rank` (à placer en tête du tri) ; sans recherche elle vaut toujours 0.
    """
    words = terms(query)
    if not words:
        return queryset.annotate(**{RANK_FIELD: Value(0, output_field=IntegerField())})
    aliases = {column: f'_n_{index}' for index, column in enumerate((name, *other_columns))}
    queryset = queryset.annotate(**{alias: indexed(column) for column, alias in aliases.items()})
    for word in words:
        condition = _matches(word, aliases.values())
        for foreign_key, model, column in related:
            linked = model.objects.annotate(_n=indexed(column)).filter(_matches(word, ['_n'])).values('pk')
            condition |= Q(**{f'{foreign_key}__in': linked})
        queryset = queryset.filter(condition)
    return queryset.annotate(**{RANK_FIELD: _rank(aliases[name], words)})


def beers(queryset, query):
    from ..models import Brewery
    return search(queryset, query, 'name', 'style', related=(('brewery_id', Brewery, 'name'),))


def breweries(queryset, query):
    return search(queryset, query, 'name', 'address')


def bars(queryset, query):
    return search(queryset, query, 'name', 'address')


def members(queryset, query):
    return search(queryset, query, 'username')
