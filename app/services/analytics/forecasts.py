"""Prévisions : où va l'activité, quels styles montent, quels mois sont porteurs.

Volontairement simples (tendance linéaire, fourchette à 80 %, indice saisonnier) et affichées avec leur fiabilité : une prévision sans
historique suffisant est pire que pas de prévision. Chaque bloc dit combien de mois d'historique il utilise.
"""
from collections import defaultdict

from django.db.models import Count, Min
from django.db.models.functions import TruncMonth

from .formatting import fr
from ...domain.styles import split_styles
from ...models import BeerSpot, BeerUser, Drinks
from .blocks import Chart, Kpi, Note, Table
from .periods import Period
from .series import count_series, forecast, linear_trend, month_name, trend_chart, trend_strength
from .tastes import MIN_STYLE_VOLUME

MIN_RELIABLE_R2 = 0.4
RISING = 5.0      # % de variation mensuelle au-delà de laquelle une tendance est jugée nette
TOP_STYLES = 15
AHEAD = 3


def _month_index(value):
    return value.year * 12 + value.month - 1


def _months_of_history(today):
    first = Drinks.objects.aggregate(first=Min('date'))['first']
    return 0 if first is None else _month_index(today) - _month_index(first) + 1


def style_momentum(period):
    """Pour chaque style : tendance mensuelle, prévision des prochains mois et fiabilité (R²) — toujours au mois, quelle que soit la granularité."""
    monthly = Period(period.months, 'month')
    buckets = monthly.buckets()
    by_style = defaultdict(lambda: defaultdict(int))
    rows = Drinks.objects.filter(date__gte=monthly.start).annotate(bucket=TruncMonth('date')).values('beer__style', 'bucket').annotate(n=Count('pk'))
    for row in rows:
        bucket = row['bucket'].date() if hasattr(row['bucket'], 'date') else row['bucket']
        for style in split_styles(row['beer__style']):
            by_style[style][bucket] += row['n']

    table, bars = [], []
    for style, counts in by_style.items():
        series = [counts.get(bucket, 0) for bucket in buckets]
        total = sum(series)
        if total < MIN_STYLE_VOLUME:
            continue
        complete = series[:-1]
        trend = linear_trend(complete)
        r2 = trend_strength(complete)
        mean = sum(complete) / len(complete) if complete else 0
        monthly_change = trend[0] / mean * 100 if trend and mean else None
        if monthly_change is None or r2 is None:
            verdict = 'Historique insuffisant'
        elif r2 < MIN_RELIABLE_R2:
            verdict = 'Irrégulier : pas de tendance fiable'
        elif monthly_change >= RISING:
            verdict = 'En hausse nette'
        elif monthly_change <= -RISING:
            verdict = 'En baisse nette'
        else:
            verdict = 'Stable'
        ahead = sum(forecast(series, AHEAD + 1)[1:])  # la première valeur prévue est celle du mois en cours : on additionne les mois à venir
        table.append((total, [style, total, sum(series[-AHEAD - 1:-1]), round(ahead) if trend else '—',
                              '—' if monthly_change is None else f'{fr(round(monthly_change), signed=True)} %', '—' if r2 is None else r2, verdict]))
        if monthly_change is not None and r2 is not None and r2 >= MIN_RELIABLE_R2:
            bars.append((style, round(monthly_change, 1)))

    table.sort(key=lambda item: -item[0])
    blocks = [Table('style-forecast', 'Styles : tendance et prévision', ['Style', 'Dégustations', f'{AHEAD} derniers mois', f'Prévision {AHEAD} mois', 'Tendance / mois', 'Fiabilité (R²)', 'Verdict'],
                    [row for _, row in table[:TOP_STYLES]],
                    subtitle=f'Au moins {MIN_STYLE_VOLUME} dégustations. Fiabilité : part de la variation expliquée par la tendance (en dessous de {MIN_RELIABLE_R2}, la prévision n\'est pas fiable)')]
    if bars:
        bars.sort(key=lambda item: -item[1])
        blocks.append(Chart('style-momentum', 'Styles à suivre : variation mensuelle', 'hbar', [name for name, _ in bars[:12]],
                            [{'name': 'Variation par mois (%)', 'data': [value for _, value in bars[:12]]}],
                            subtitle='Seulement les tendances fiables ; positif : le style gagne des amateurs chaque mois'))
    return blocks


def _seasonal_index(today):
    """Indice saisonnier : activité moyenne de chaque mois du calendrier rapportée à la moyenne de tous les mois (100 = moyenne)."""
    first = Drinks.objects.aggregate(first=Min('date'))['first']
    if first is None:
        return []
    current = today.replace(day=1)
    totals = {}
    for row in Drinks.objects.filter(date__lt=current).annotate(bucket=TruncMonth('date')).values('bucket').annotate(n=Count('pk')):
        totals[row['bucket'].date() if hasattr(row['bucket'], 'date') else row['bucket']] = row['n']
    if len(totals) < 12:
        return [Note("Indice saisonnier indisponible : il faut au moins 12 mois complets d'historique (et idéalement 24) pour distinguer la saison de la croissance.")]
    overall = sum(totals.values()) / len(totals)
    per_month = defaultdict(list)
    for bucket, count in totals.items():
        per_month[bucket.month].append(count)
    index = [round(sum(per_month[m]) / len(per_month[m]) / overall * 100) if per_month[m] else None for m in range(1, 13)]
    years = len(totals) / 12
    blocks = [Chart('seasonal-index', 'Indice saisonnier de l\'activité', 'bar', [month_name(m) for m in range(1, 13)], [{'name': 'Indice (100 = moyenne)', 'data': index}],
                    subtitle=f'Calculé sur {len(totals)} mois complets. Au-dessus de 100 : mois porteur, pour caler lancements et promotions')]
    if years < 2:
        blocks.append(Note("Moins de deux ans d'historique : un mois n'a été observé qu'une fois, l'indice mélange saison et croissance. À lire avec prudence."))
    return blocks


def build(period, params):
    today = period.today
    history = _months_of_history(today)
    blocks = [
        Kpi('Historique disponible', f'{history} mois', hint='depuis la première dégustation enregistrée'),
        Kpi('Fiabilité des prévisions', 'Bonne' if history >= 18 else 'Moyenne' if history >= 9 else 'Faible',
            hint='bonne à partir de 18 mois, faible sous 9 mois : une courbe jeune est dominée par la croissance de lancement'),
        Note("Prévision = prolongement de la tendance linéaire des intervalles complets (le dernier, en cours, est exclu). La fourchette indique 80 % des cas "
             "plausibles : plus elle est large, moins la prévision est utile. Aucun effet de saison ni événement exceptionnel n'est modélisé ici."),
    ]
    series = (
        ('forecast-drinks', 'Dégustations', Drinks.objects.all(), 'date', None),
        ('forecast-active', 'Membres actifs', Drinks.objects.all(), 'date', Count('drinker', distinct=True)),
        ('forecast-users', 'Nouveaux membres', BeerUser.objects.all(), 'created_at', None),
        ('forecast-spots', 'Lieux placés sur la carte', BeerSpot.objects.all(), 'date', None),
    )
    for chart_id, title, queryset, field, aggregate in series:
        values = count_series(queryset, field, period, aggregate)
        blocks.append(trend_chart(chart_id, f'Prévision · {title}', values, period, unit_name=title, band=True))

    blocks += style_momentum(period)
    blocks += _seasonal_index(today)
    return blocks
