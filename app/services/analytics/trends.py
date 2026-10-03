"""Tendances : évolution de l'activité dans le temps, avec moyenne mobile et prévision indicative."""
from collections import Counter

from django.db.models import Count, Min

from ...models import Bar, BeerSpot, BeerUser, Brewery, Drinks
from .blocks import Kpi, Note
from .date import date_range
from .series import count_series, growth, trend_chart

def _metrics():
    """(id, titre, queryset, champ date, agrégat éventuel) de chaque série suivie."""
    return [
        ('drinks', 'Dégustations', Drinks.objects.all(), 'date', None),
        ('active', 'Membres actifs (au moins une dégustation)', Drinks.objects.all(), 'date', Count('drinker_id', distinct=True)),
        ('users', 'Nouveaux membres', BeerUser.objects.all(), 'created_at', None),
        ('spots', 'Lieux placés sur la carte', BeerSpot.objects.all(), 'date', None),
        ('breweries', 'Nouvelles brasseries', Brewery.objects.all(), 'created_at', None),
        ('bars', 'Nouveaux bars', Bar.objects.all(), 'created_at', None),
    ]


def _new_beers_series(period):
    """Bières par date de première dégustation : `Beer` n'a pas de date de création, mais chaque bière naît avec sa première note."""
    first_tasting = Drinks.objects.filter(beer_id__is_deleted=False).values('beer_id').annotate(first=Min('date')).values_list('first', flat=True)
    counts = Counter(period.bucket_start(day) for day in first_tasting if day >= period.start)
    return [counts.get(bucket, 0) for bucket in period.buckets()]


def build(period, params):
    blocks, kpis, charts = [], [], []
    new_beers = _new_beers_series(period)
    charts.append(trend_chart('trend-beers', 'Nouvelles bières au catalogue', new_beers, period, unit_name='Nouvelles bières'))
    kpis.append(Kpi('Nouvelles bières au catalogue', sum(new_beers), hint='date de première dégustation'))
    for key, title, queryset, field_name, aggregate in _metrics():
        values = count_series(queryset, field_name, period, aggregate)
        charts.append(trend_chart(f'trend-{key}', title, values, period, unit_name=title))

        if aggregate is None:  # les distincts ne s'additionnent pas d'un intervalle à l'autre
            current = sum(values)
            previous = date_range(queryset, field_name, period.previous_start, period.start).count()
            kpis.append(Kpi(title, current, growth(current, previous), hint=f'vs {period.months} mois précédents'))

    blocks.append(Note(
        "Les prévisions prolongent la tendance linéaire des intervalles complets (le dernier, en cours, est exclu). "
        "Elles sont indicatives : fiables seulement avec assez d'historique et sans événement exceptionnel."
    ))
    return kpis + blocks + charts
