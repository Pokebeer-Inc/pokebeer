"""Catalogue fermé des données interrogeables : jeux de données, dimensions (regrouper par) et mesures (calculer).

Ajouter une donnée = ajouter une entrée ici. Aucune dimension ne permet d'identifier un membre (ni pseudo, ni e-mail) ;
les regroupements non temporels sont soumis au k-anonymat (voir engine).
"""
from dataclasses import dataclass, field
from typing import Callable, Optional

from django.db.models import Avg, Count, F
from django.db.models.functions import ExtractIsoWeekDay, ExtractMonth

from ....models import Bar, BeerSpot, BeerUser, Brewery, Drinks, UserAchievementState
from ...achievements import TIER_NAMES
from ..habits import WEEKDAYS
from ..series import month_name


@dataclass(frozen=True)
class Measure:
    label: str
    aggregate: Callable  # dataset -> expression d'agrégation
    decimals: int = 0


@dataclass(frozen=True)
class Dimension:
    label: str
    kind: str  # 'time' | 'fixed' | 'category'
    expression: Callable = None            # (period, dataset) -> expression de regroupement
    categories: Callable = None            # (period) -> liste ordonnée des valeurs possibles (time/fixed)
    to_label: Callable = str               # valeur -> libellé affiché


@dataclass(frozen=True)
class Dataset:
    label: str
    queryset: Callable
    measures: dict
    dimensions: dict
    date_field: Optional[str] = None       # champ filtré par la période ; None = jeu de données sans date
    member_field: Optional[str] = None     # champ « membre » : sert uniquement à compter des membres distincts
    brewery_path: Optional[str] = None     # chemin du slug de brasserie, si le filtre « brasserie » s'applique


def _time():
    return Dimension(
        'Période', 'time',
        expression=lambda period, dataset: period.trunc(dataset.date_field),
        categories=lambda period: period.buckets(),
    )


def _field(label, path, empty='Non renseigné'):
    return Dimension(label, 'category', expression=lambda period, dataset: F(path), to_label=lambda v: str(v) if v not in (None, '') else empty)


WEEKDAY = Dimension('Jour de la semaine', 'fixed', expression=lambda period, dataset: ExtractIsoWeekDay(dataset.date_field),
                    categories=lambda period: list(range(1, 8)), to_label=lambda v: WEEKDAYS[v - 1])
MONTH_OF_YEAR = Dimension('Mois de l\'année', 'fixed', expression=lambda period, dataset: ExtractMonth(dataset.date_field),
                          categories=lambda period: list(range(1, 13)), to_label=month_name)

VERIFIED = Dimension('Statut', 'category', expression=lambda period, dataset: F('is_verified'),
                     to_label=lambda v: 'Vérifié' if v else 'À vérifier')

COUNT = lambda label: Measure(label, lambda dataset: Count('pk'))
DISTINCT_MEMBERS = Measure('Membres distincts', lambda dataset: Count(dataset.member_field, distinct=True))

CATALOG = {
    'drinks': Dataset(
        'Dégustations', Drinks.objects.all, date_field='date', member_field='drinker_id', brewery_path='beer_id__brewery_id__slug',
        measures={
            'count': COUNT('Dégustations'),
            'members': DISTINCT_MEMBERS,
            'avg_note': Measure('Note moyenne', lambda dataset: Avg('note'), decimals=2),
            'beers': Measure('Bières distinctes', lambda dataset: Count('beer_id', distinct=True)),
        },
        dimensions={
            'time': _time(), 'weekday': WEEKDAY, 'month_of_year': MONTH_OF_YEAR,
            'style': _field('Style (tel que saisi)', 'beer_id__style', 'Sans style'),
            'brewery': _field('Brasserie', 'beer_id__brewery_id__name'),
            'beer': _field('Bière', 'beer_id__name'),
            'rating': _field('Note', 'note', 'Non noté'),
        },
    ),
    'spots': Dataset(
        'Lieux sur la carte', BeerSpot.objects.all, date_field='date', member_field='user_id',
        measures={'count': COUNT('Lieux'), 'members': DISTINCT_MEMBERS},
        dimensions={'time': _time(), 'weekday': WEEKDAY, 'month_of_year': MONTH_OF_YEAR},
    ),
    'members': Dataset(
        'Nouveaux membres', BeerUser.objects.all, date_field='created_at',
        measures={'count': COUNT('Nouveaux membres')},
        dimensions={'time': _time(), 'weekday': WEEKDAY, 'month_of_year': MONTH_OF_YEAR},
    ),
    'breweries': Dataset(
        'Brasseries', Brewery.objects.all, date_field='created_at',
        measures={'count': COUNT('Brasseries')},
        dimensions={'time': _time(), 'verified': VERIFIED},
    ),
    'bars': Dataset(
        'Bars', Bar.objects.all, date_field='created_at',
        measures={'count': COUNT('Bars')},
        dimensions={'time': _time(), 'verified': VERIFIED},
    ),
    'trophies': Dataset(
        'Trophées (progression des membres)', UserAchievementState.objects.all, member_field='user_id',
        measures={'count': COUNT('Membres')},
        dimensions={
            'trophy': _field('Trophée', 'achievement_name'),
            'tier': Dimension('Palier', 'category', expression=lambda period, dataset: F('tier_level'),
                              to_label=lambda v: TIER_NAMES[min(v, len(TIER_NAMES) - 1)]),
        },
    ),
}
