"""Catalogue fermé des données interrogeables : jeux de données, dimensions (regrouper par) et mesures (calculer).

Ajouter une donnée = ajouter une entrée ici. Aucune dimension ne permet d'identifier un membre (ni pseudo, ni e-mail) ;
les regroupements non temporels sont soumis au k-anonymat (voir engine).
"""
from dataclasses import dataclass
from collections.abc import Callable


from django.db.models import Avg, Case, Count, F, Sum, Value, When
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay, ExtractMonth
from django.utils import timezone

from ....models import (ActivityDay, Bar, Beer, BeerSpot, BeerUser, Brewery, CatalogMiss, DrinkReaction, Drinks, EstablishmentClaim, Notification, PageView,
                        QuotaUsage, Report, UserAchievementState, UserFollow)
from ...members.achievements import ACHIEVEMENT_NAMES, TIER_NAMES
from ..habits import WEEKDAYS
from ..profiles import AGE_BANDS, COMPANY_LABELS, FORMAT_LABELS, GENDER_LABELS, PRICE_BUCKETS, VENUE_LABELS
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
    scope: Callable = None                 # (dataset) -> filtres à appliquer avant de regrouper (ex. exclure les membres opposés aux statistiques)


@dataclass(frozen=True)
class Dataset:
    label: str
    queryset: Callable
    measures: dict
    dimensions: dict
    date_field: str | None = None       # champ filtré par la période ; None = jeu de données sans date
    member_field: str | None = None     # champ « membre » : sert uniquement à compter des membres distincts
    brewery_path: str | None = None     # chemin du slug de brasserie, si le filtre « brasserie » s'applique


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

def _labelled(label, path, labels, empty='Non renseigné', scope=None):
    """Regroupement par un champ à valeurs connues : le code stocké est remplacé par son libellé."""
    return Dimension(label, 'category', expression=lambda period, dataset: F(path), to_label=lambda v: labels.get(v, v) if v not in (None, '') else empty,
                     scope=scope)


def _member_path(dataset, field):
    """Chemin d'un champ du membre depuis le jeu de données : direct pour les membres, via le dégustateur pour les dégustations."""
    return f'drinker__{field}' if dataset.member_field == 'drinker' else field


def _opted_in(dataset):
    """Âge et genre ne servent que pour les membres qui acceptent les statistiques anonymes."""
    return {_member_path(dataset, 'demographic_stats'): True}


def _years_ago(day, years):
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 février
        return day.replace(year=day.year - years, day=28)


def _age_band(period, dataset):
    """Tranche d'âge calculée à la volée à partir de la date de naissance (jamais exposée) : (0, 24) = né il y a moins de 25 ans."""
    today = timezone.localdate()
    path = _member_path(dataset, 'birth_date')
    whens = []
    for low, high, label in AGE_BANDS:
        conditions = {f'{path}__lte': _years_ago(today, low)}
        if high < 200:
            conditions[f'{path}__gt'] = _years_ago(today, high + 1)
        whens.append(When(then=Value(label), **conditions))
    return Case(*whens, default=Value('Non renseigné'))


def _price_bucket(period, dataset):
    whens = [When(price__gte=low, price__lt=high, then=Value(label)) for low, high, label in PRICE_BUCKETS]
    return Case(*whens, default=Value('Non renseigné'))


AGE = Dimension('Tranche d\'âge', 'category', expression=_age_band, scope=_opted_in)
HOUR = Dimension('Heure d\'enregistrement', 'fixed', expression=lambda period, dataset: ExtractHour('created_at'),
                 categories=lambda period: list(range(24)), to_label=lambda v: f'{v} h')

COUNT = lambda label: Measure(label, lambda dataset: Count('pk'))
DISTINCT_MEMBERS = Measure('Membres distincts', lambda dataset: Count(dataset.member_field, distinct=True))

CATALOG = {
    'drinks': Dataset(
        'Dégustations', Drinks.objects.all, date_field='date', member_field='drinker', brewery_path='beer__brewery__slug',
        measures={
            'count': COUNT('Dégustations'),
            'members': DISTINCT_MEMBERS,
            'avg_note': Measure('Note moyenne', lambda dataset: Avg('note'), decimals=2),
            'beers': Measure('Bières distinctes', lambda dataset: Count('beer', distinct=True)),
            'avg_price': Measure('Prix moyen payé (€)', lambda dataset: Avg('price'), decimals=2),
            'priced': Measure('Prix renseignés', lambda dataset: Count('price')),
        },
        dimensions={
            'time': _time(), 'weekday': WEEKDAY, 'month_of_year': MONTH_OF_YEAR, 'hour': HOUR,
            'style': _field('Style (tel que saisi)', 'beer__style', 'Sans style'),
            'brewery': _field('Brasserie', 'beer__brewery__name'),
            'beer': _field('Bière', 'beer__name'),
            'rating': _field('Note', 'note', 'Non noté'),
            'venue': _labelled('Lieu de dégustation', 'venue_type', VENUE_LABELS),
            'company': _labelled('Compagnie', 'company', COMPANY_LABELS),
            'format': _labelled('Format servi', 'serving_format', FORMAT_LABELS),
            'price_bucket': Dimension('Tranche de prix', 'category', expression=_price_bucket),
            'age': AGE,
            'gender': _labelled('Genre', 'drinker__gender', {**GENDER_LABELS, 'nsp': 'Non précisé'}, scope=_opted_in),
            'family': _field('Famille de style', 'beer__primary_style__family__name', 'Style non reconnu'),
        },
    ),
    'spots': Dataset(
        'Lieux sur la carte', BeerSpot.objects.all, date_field='date', member_field='user_id',
        measures={'count': COUNT('Lieux'), 'members': DISTINCT_MEMBERS},
        dimensions={'time': _time(), 'weekday': WEEKDAY, 'month_of_year': MONTH_OF_YEAR},
    ),
    'members': Dataset(
        'Nouveaux membres', BeerUser.objects.all, date_field='created_at', member_field='pk',
        measures={'count': COUNT('Nouveaux membres')},
        dimensions={'time': _time(), 'weekday': WEEKDAY, 'month_of_year': MONTH_OF_YEAR, 'age': AGE,
                    'gender': _labelled('Genre', 'gender', {**GENDER_LABELS, 'nsp': 'Non précisé'}, scope=_opted_in)},
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
    'reactions': Dataset(
        'Pouces sur les avis', DrinkReaction.objects.all, date_field='created_at', member_field='user_id',
        measures={'count': COUNT('Pouces'), 'members': DISTINCT_MEMBERS},
        dimensions={'time': _time(), 'weekday': WEEKDAY, 'month_of_year': MONTH_OF_YEAR,
                    'kind': Dimension('Sens', 'category', expression=lambda period, dataset: F('is_like'), to_label=lambda v: 'Pouce en l\'air' if v else 'Pouce en bas')},
    ),
    'follows': Dataset(
        'Abonnements entre membres', UserFollow.objects.all, date_field='created_at', member_field='follower_id',
        measures={'count': COUNT('Abonnements'), 'members': DISTINCT_MEMBERS},
        dimensions={'time': _time(), 'weekday': WEEKDAY, 'month_of_year': MONTH_OF_YEAR},
    ),
    'notifications': Dataset(
        'Notifications', Notification.objects.all, date_field='created_at', member_field='recipient_id',
        measures={'count': COUNT('Notifications'), 'members': DISTINCT_MEMBERS},
        dimensions={'time': _time(), 'weekday': WEEKDAY, 'month_of_year': MONTH_OF_YEAR,
                    'type': _labelled('Type', 'notif_type', dict(Notification.NOTIFICATION_TYPES)),
                    'read': Dimension('Lue', 'category', expression=lambda period, dataset: F('is_read'), to_label=lambda v: 'Lue' if v else 'Non lue')},
    ),
    'usage': Dataset(
        'Services IA et scan (quotas)', QuotaUsage.objects.all, date_field='day', member_field='user_id',
        measures={'calls': Measure('Appels', lambda dataset: Sum('count')), 'members': DISTINCT_MEMBERS},
        dimensions={'time': _time(), 'weekday': WEEKDAY, 'month_of_year': MONTH_OF_YEAR,
                    'scope': _labelled('Service', 'scope', {'chat': 'Chat (Gaétan)', 'label': 'Lecture d\'étiquette', 'ean': 'Code-barres'})},
    ),
    'claims': Dataset(
        'Revendications d\'établissement', EstablishmentClaim.objects.all, date_field='created_at', member_field='claimant_id',
        measures={'count': COUNT('Revendications')},
        dimensions={'time': _time(), 'status': _labelled('Statut', 'status', dict(EstablishmentClaim.Status.choices)),
                    'target': Dimension('Type d\'établissement', 'category',
                                        expression=lambda period, dataset: Case(When(brewery__isnull=False, then=Value('Brasserie')), default=Value('Bar')))},
    ),
    'reports': Dataset(
        'Signalements', Report.objects.all, date_field='created_at', member_field='reporter_id',
        measures={'count': COUNT('Signalements')},
        dimensions={'time': _time(), 'reason': _labelled('Motif', 'reason', dict(Report.REASON_CHOICES)),
                    'status': _labelled('Statut', 'status', dict(Report.STATUS_CHOICES))},
    ),
    'beers': Dataset(
        'Bières du catalogue', lambda: Beer.objects.filter(is_deleted=False), brewery_path='brewery__slug',
        measures={'count': COUNT('Bières'), 'avg_degree': Measure('Degré moyen (%)', lambda dataset: Avg('degree'), decimals=1),
                  'avg_ibu': Measure('Amertume moyenne (IBU)', lambda dataset: Avg('bitterness'), decimals=0)},
        dimensions={'style': _field('Style', 'style', 'Sans style'), 'family': _field('Famille de style', 'primary_style__family__name', 'Style non reconnu'),
                    'brewery': _field('Brasserie', 'brewery__name'), 'verified': VERIFIED},
    ),
    'views': Dataset(
        'Vues des fiches', PageView.objects.all, date_field='day',
        measures={'views': Measure('Vues', lambda dataset: Sum('views')), 'visitors': Measure('Visiteurs (somme des jours)', lambda dataset: Sum('visitors'))},
        dimensions={'time': _time(), 'weekday': WEEKDAY, 'month_of_year': MONTH_OF_YEAR, 'kind': _labelled('Type de fiche', 'kind', dict(PageView.Kind.choices))},
    ),
    'activity': Dataset(
        'Jours d\'activité des membres', ActivityDay.objects.all, date_field='day', member_field='user_id',
        measures={'members': DISTINCT_MEMBERS, 'days': COUNT('Jours d\'activité')},
        dimensions={'time': _time(), 'weekday': WEEKDAY, 'month_of_year': MONTH_OF_YEAR},
    ),
    'misses': Dataset(
        'Demandes sans résultat', CatalogMiss.objects.all, date_field='day',
        measures={'calls': Measure('Demandes', lambda dataset: Sum('count'))},
        dimensions={'time': _time(), 'source': _labelled('Origine', 'source', dict(CatalogMiss.Source.choices)), 'term': _field('Terme ou code', 'key', 'Étiquette')},
    ),
    'trophies': Dataset(
        'Trophées (progression des membres)', UserAchievementState.objects.all, member_field='user_id',
        measures={'count': COUNT('Membres')},
        dimensions={
            'trophy': Dimension('Trophée', 'category', expression=lambda period, dataset: F('achievement_slug'),
                                to_label=lambda v: ACHIEVEMENT_NAMES.get(v, v or 'Non renseigné')),
            'tier': Dimension('Palier', 'category', expression=lambda period, dataset: F('tier_level'),
                              to_label=lambda v: TIER_NAMES[min(v, len(TIER_NAMES) - 1)]),
        },
    ),
}
