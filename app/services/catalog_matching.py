"""Détection des doublons du catalogue : une seule règle, partagée par le formulaire d'ajout, la vérification en direct (API) et
l'écran d'administration. Les clés de comparaison viennent de match_keys ; les candidats sont retrouvés par index (clé stricte
égale, ou similarité trigramme de la clé large), puis départagés ici avec le contexte complet.

Verdicts, du plus fort au plus faible :
- SAME : même nom une fois les différences sans importance retirées. Une brasserie identique est réutilisée ; une bière identique
  dans la même brasserie est refusée (on renvoie vers la fiche existante).
- PROBABLE : très proche (« Microbrasserie du Coin » / « Brasserie du Coin », « Leffe Blond » / « Leffe Blonde »). Le membre doit
  choisir l'existant ou confirmer que c'est différent : la confirmation est un jeton signé, lié à ce nom et à ces candidats.
- ELSEWHERE : même nom de bière chez une autre brasserie. Information seulement, jamais bloquant.

Homonymes : deux établissements de même nom dans deux villes (code postal ou commune différents) sont distincts, et ne se gênent jamais. Quand
le lieu de l'un des deux est inconnu, on ne peut pas trancher : le nom identique reste SAME tant que le membre n'a pas donné son code postal,
puis devient PROBABLE (« est-ce la même ? ») si la fiche existante n'a pas de lieu, pour que le membre puisse confirmer qu'il s'agit d'une autre.
"""
from dataclasses import dataclass
from enum import IntEnum

from django.contrib.postgres.search import TrigramSimilarity
from django.core import signing
from django.db import connection
from django.db.models import Q

from ..models import Bar, Beer, Brewery
from . import match_keys as keys, search

PLACE_CANDIDATES = 10
BEER_CANDIDATES = 40
PLACE_MODELS = {keys.BREWERY: Brewery, keys.BAR: Bar}
SAME_PLACE, OTHER_PLACE, UNKNOWN_PLACE = 'same', 'different', 'unknown'
TOKEN_SALT = 'catalog-duplicate-confirmation'
TOKEN_MAX_AGE = 3600  # une confirmation vaut une heure
MAX_PAIRS = 500       # borne de l'écran d'administration


class Level(IntEnum):
    NONE = 0
    ELSEWHERE = 1
    PROBABLE = 2
    SAME = 3


@dataclass(frozen=True)
class Candidate:
    obj: object      # Brewery ou Beer existant
    level: Level
    score: float


@dataclass(frozen=True)
class Report:
    kind: str                # keys.BREWERY ou keys.BEER
    key: str                 # ce à quoi se lie la confirmation
    candidates: tuple = ()
    token: str = ''          # jeton de confirmation (vide hors cas PROBABLE)

    @property
    def level(self):
        """Niveau bloquant le plus élevé : ELSEWHERE n'est qu'une information."""
        blocking = [c.level for c in self.candidates if c.level >= Level.PROBABLE]
        return max(blocking, default=Level.NONE)

    @property
    def same(self):
        return next((c for c in self.candidates if c.level == Level.SAME), None)

    @property
    def probables(self):
        return [c for c in self.candidates if c.level == Level.PROBABLE]

    @property
    def elsewhere(self):
        return [c for c in self.candidates if c.level == Level.ELSEWHERE]


@dataclass(frozen=True)
class Inspection:
    brewery: Report
    beer: Report
    postal_typed: bool = False  # le membre a donné le code postal de sa brasserie

    @property
    def reusable_brewery(self):
        """Brasserie existante à utiliser telle quelle (verdict SAME), sinon None."""
        match = self.brewery.same
        return match.obj if match else None


class DuplicateFound(Exception):
    """L'ajout est refusé tant que le membre n'a pas choisi : `messages` explique pourquoi, `inspection` donne les candidats."""

    def __init__(self, inspection, messages):
        super().__init__(' '.join(messages))
        self.inspection = inspection
        self.messages = messages


def _sign(kind, key, ids):
    return signing.dumps({'kind': kind, 'key': key, 'ids': sorted(ids)}, salt=TOKEN_SALT, compress=False)


def _with_token(kind, key, candidates):
    probable = [c.obj.pk for c in candidates if c.level == Level.PROBABLE]
    return Report(kind, key, tuple(candidates), _sign(kind, key, probable) if probable else '')


def confirmed(report, token):
    """Le membre a-t-il confirmé, pour CE nom et CES candidats, que son entrée est différente de l'existant ?"""
    if not token or not report.token:
        return False
    try:
        payload = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    except signing.BadSignature:
        return False
    return payload == signing.loads(report.token, salt=TOKEN_SALT)


def _ordered(candidates):
    return sorted(candidates, key=lambda c: (-c.level, -c.score, c.obj.name))


def place_relation(postal_code, city, obj):
    """Même lieu, lieux différents ou inconnu, entre ce que le membre a saisi et la fiche existante (code postal d'abord, puis commune)."""
    typed_postal, typed_city = postal_code or '', search.normalize(city or '')
    known_postal, known_city = obj.postal_code or '', search.normalize(obj.city or '')
    if typed_postal and known_postal and typed_postal == known_postal:
        return SAME_PLACE
    if typed_city and known_city:
        return SAME_PLACE if typed_city == known_city else OTHER_PLACE
    if typed_postal and known_postal:
        return OTHER_PLACE  # codes postaux différents, communes inconnues d'un côté ou de l'autre : deux lieux
    return UNKNOWN_PLACE


def find_place(kind, name, postal_code='', city='', exclude_pk=None):
    """Brasseries (kind=keys.BREWERY) ou bars (keys.BAR) qui ressemblent à `name` dans le même lieu (ou à un lieu inconnu)."""
    strict, loose = keys.strict_key(name, kind), keys.loose_key(name, kind)
    if not loose:
        return Report(kind, '')
    wanted = keys.loose_tokens(name, kind)
    rows = PLACE_MODELS[kind].objects.filter(Q(name_key=strict) | Q(match_key__trigram_similar=loose))
    if exclude_pk:
        rows = rows.exclude(pk=exclude_pk)
    rows = rows.annotate(similarity=TrigramSimilarity('match_key', loose)).order_by('-similarity', 'name')[:PLACE_CANDIDATES]
    candidates = []
    for row in rows:
        relation = place_relation(postal_code, city, row)
        if relation == OTHER_PLACE:
            continue  # homonyme d'une autre ville : un autre établissement
        if row.name_key == strict:
            # Le membre a donné son lieu mais la fiche existante n'en a pas : on ne peut pas dire que c'est la même, il doit choisir
            level = Level.PROBABLE if (postal_code and relation == UNKNOWN_PLACE and not (row.postal_code or row.city)) else Level.SAME
            candidates.append(Candidate(row, level, 1.0))
            continue
        score = keys.similarity(wanted, row.match_key.split())
        if score >= keys.PROBABLE_SIMILARITY:
            candidates.append(Candidate(row, Level.PROBABLE, score))
    return _with_token(kind, f"{strict}|{postal_code or ''}", _ordered(candidates))


def find_brewery(name, postal_code='', city='', exclude_pk=None):
    return find_place(keys.BREWERY, name, postal_code, city, exclude_pk)


def find_bar(name, postal_code='', city='', exclude_pk=None):
    return find_place(keys.BAR, name, postal_code, city, exclude_pk)


def _beer_tokens(name_key, brewery_name):
    """Mots d'une bière sans ceux de sa brasserie (« BrewDog Punk IPA » chez BrewDog se compare comme « Punk IPA »)."""
    return keys.without(name_key.split(), keys.strict_tokens(brewery_name, keys.BREWERY))


def find_beer(name, brewery_name, brewery_pks=(), exclude_pk=None):
    """Bières proches de `name`. `brewery_pks` : brasseries existantes que la bière saisie désigne (ses homonymes y sont des doublons)."""
    loose = keys.loose_key(name, keys.BEER)
    if not loose:
        return Report(keys.BEER, '')
    pks = set(brewery_pks)
    key = f"{keys.strict_key(name, keys.BEER)}|{','.join(map(str, sorted(pks)))}"
    wanted = keys.without(keys.loose_tokens(name, keys.BEER), keys.strict_tokens(brewery_name, keys.BREWERY))
    condition = Q(name_key=keys.strict_key(name, keys.BEER)) | Q(match_key__trigram_similar=loose)
    if pks:
        condition |= Q(brewery_id__in=pks)  # toutes les bières de la brasserie : le nom de la brasserie recopié fausse la similarité
    rows = Beer.objects.filter(condition, is_deleted=False).select_related('brewery_id').annotate(similarity=TrigramSimilarity('match_key', loose))
    if exclude_pk:
        rows = rows.exclude(pk=exclude_pk)
    candidates = []
    for row in rows.order_by('-similarity', 'name')[:BEER_CANDIDATES]:
        score = keys.similarity(wanted, _beer_tokens(row.match_key, row.brewery_id.name))
        same_brewery = row.brewery_id_id in pks
        if score == 1.0:
            candidates.append(Candidate(row, Level.SAME if same_brewery else Level.ELSEWHERE, 1.0))
        elif same_brewery and score >= keys.PROBABLE_SIMILARITY:
            candidates.append(Candidate(row, Level.PROBABLE, score))
    return _with_token(keys.BEER, key, _ordered(candidates))


def inspect(name, brewery_name, exclude_beer_pk=None, brewery_confirmed=False, postal_code='', city=''):
    """Rapports sur la brasserie saisie (avec son lieu s'il est connu) et sur la bière saisie. Si le membre a confirmé que sa brasserie est une
    autre que celles qui lui ressemblent, la bière n'est plus comparée à leurs bières."""
    brewery = find_brewery(brewery_name, postal_code, city)
    if brewery.same:
        pks = {brewery.same.obj.pk}
    elif brewery_confirmed:
        pks = set()
    else:
        pks = {c.obj.pk for c in brewery.candidates if c.level == Level.PROBABLE}
    return Inspection(brewery, find_beer(name, brewery_name, pks, exclude_beer_pk), postal_typed=bool(postal_code))


def _describe(report, noun):
    first = report.candidates[0].obj
    if noun == keys.BEER:
        return f"« {first.name} » ({first.brewery_id.name})"
    return f"« {first.name} »" + (f" ({first.postal_code} {first.city})".replace("  ", " ") if first.postal_code or first.city else "")


def decide(name, brewery_name, exclude_beer_pk=None, confirm_brewery='', confirm_beer='', postal_code='', city=''):
    """Inspection si l'ajout peut se poursuivre ; lève DuplicateFound sinon (messages à afficher, candidats à proposer)."""
    brewery_report = find_brewery(brewery_name, postal_code, city)
    brewery_ok = brewery_report.level != Level.PROBABLE or confirmed(brewery_report, confirm_brewery)
    inspection = inspect(
        name, brewery_name, exclude_beer_pk, brewery_confirmed=brewery_report.level == Level.PROBABLE and brewery_ok, postal_code=postal_code, city=city,
    )
    messages = []
    if not brewery_ok:
        messages.append(f"Une brasserie très proche existe déjà : {_describe(brewery_report, keys.BREWERY)}. Utilisez-la, ou confirmez que c'est une autre brasserie.")
    beer = inspection.beer
    if beer.level == Level.SAME:
        messages.append(f"Cette bière existe déjà : {_describe(beer, keys.BEER)}.")
    elif beer.level == Level.PROBABLE and not confirmed(beer, confirm_beer):
        messages.append(f"Une bière très proche existe déjà : {_describe(beer, keys.BEER)}. Utilisez-la, ou confirmez que c'est une autre bière.")
    if messages:
        raise DuplicateFound(inspection, messages)
    return inspection


# ---------------------------------------------------------------------------------------------------------------------------
# Écran d'administration : paires déjà présentes dans le catalogue
# ---------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Pair:
    first: object
    second: object
    level: Level
    score: float


def _pair_ids(sql):
    with connection.cursor() as cursor:
        cursor.execute(sql, [MAX_PAIRS])
        return cursor.fetchall()


def duplicate_places(kind):
    """Paires de brasseries (ou de bars) dont les noms se confondent dans un même lieu (ou à un lieu inconnu) ; les homonymes de villes
    différentes ne sont pas des doublons."""
    model = PLACE_MODELS[kind]
    table = model._meta.db_table
    ids = _pair_ids(f"SELECT a.id, b.id FROM {table} a JOIN {table} b ON a.id < b.id AND a.name_key <> '' AND (a.name_key = b.name_key OR a.match_key %% b.match_key) ORDER BY a.id, b.id LIMIT %s")
    by_pk = model.objects.in_bulk({pk for pair in ids for pk in pair})
    pairs = []
    for first_id, second_id in ids:
        first, second = by_pk[first_id], by_pk[second_id]
        if place_relation(first.postal_code, first.city, second) == OTHER_PLACE:
            continue
        if first.name_key == second.name_key:
            pairs.append(Pair(first, second, Level.SAME, 1.0))
            continue
        score = keys.similarity(first.match_key.split(), second.match_key.split())
        if score >= keys.PROBABLE_SIMILARITY:
            pairs.append(Pair(first, second, Level.PROBABLE, score))
    return sorted(pairs, key=lambda p: (-p.level, -p.score))


def duplicate_breweries():
    return duplicate_places(keys.BREWERY)


def duplicate_bars():
    return duplicate_places(keys.BAR)


def duplicate_beers():
    """Paires de bières d'une même brasserie dont les noms se confondent (même nom chez deux brasseries est permis)."""
    table = Beer._meta.db_table
    ids = _pair_ids(
        f"SELECT a.id, b.id FROM {table} a JOIN {table} b ON a.id < b.id AND a.brewery_id_id = b.brewery_id_id "
        f"WHERE NOT a.is_deleted AND NOT b.is_deleted AND a.name_key <> '' AND (a.name_key = b.name_key OR a.match_key %% b.match_key) "
        f"ORDER BY a.id, b.id LIMIT %s"
    )
    by_pk = Beer.objects.select_related('brewery_id').in_bulk({pk for pair in ids for pk in pair})
    pairs = []
    for first_id, second_id in ids:
        first, second = by_pk[first_id], by_pk[second_id]
        score = keys.similarity(_beer_tokens(first.match_key, first.brewery_id.name), _beer_tokens(second.match_key, second.brewery_id.name))
        if score == 1.0:
            pairs.append(Pair(first, second, Level.SAME, 1.0))
        elif score >= keys.PROBABLE_SIMILARITY:
            pairs.append(Pair(first, second, Level.PROBABLE, score))
    return sorted(pairs, key=lambda p: (-p.level, -p.score))
