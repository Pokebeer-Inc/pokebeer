"""Consommation : dans quel contexte on boit (lieu, compagnie, format, prix, moment) et ce que cela coûte.

Ces informations sont facultatives à la saisie : le premier graphique indique la part de dégustations où chacune est renseignée, pour
savoir combien faire confiance aux suivants. Tout groupe de moins de MIN_GROUP_SIZE dégustateurs distincts est masqué.
"""
from collections import defaultdict

from django.db.models import Avg, Count
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay

from ...domain.styles import split_styles
from ...models import BeerSpot, Drinks
from .blocks import Chart, Note
from .habits import WEEKDAYS
from .privacy import MIN_GROUP_SIZE, is_publishable
from .profiles import (COMPANY_LABELS, FORMAT_LABELS, FORMAT_LITRES, HEATMAP_STYLES, PRICE_BUCKETS, VENUE_LABELS, context_blocks, coverage,
                       price_blocks)
from .spots import spot_points
from .tastes import MIN_STYLE_VOLUME

TOP = 10


def _group_average(rows, keys_of, value_of, label_of=str):
    """[(libellé, moyenne, effectif, dégustateurs)] des groupes publiables. `keys_of(row)` renvoie les groupes de la ligne (un style composé
    en compte plusieurs), `value_of(row)` la valeur à moyenner (None : ligne ignorée)."""
    groups = defaultdict(lambda: [0.0, 0, set()])
    for row in rows:
        value = value_of(row)
        if value is None:
            continue
        for key in keys_of(row):
            group = groups[key]
            group[0] += value
            group[1] += 1
            group[2].add(row['drinker'])
    return sorted(((label_of(key), total / count, count, len(drinkers)) for key, (total, count, drinkers) in groups.items()
                   if is_publishable(len(drinkers))), key=lambda item: -item[2])


def _price_rows(drinks):
    return list(drinks.filter(price__isnull=False).values('price', 'note', 'drinker', 'serving_format', 'venue_type', 'beer__style'))


def price_charts(drinks):
    rows = _price_rows(drinks)
    if not rows:
        return []
    blocks = []

    by_format = _group_average(rows, lambda r: [r['serving_format']] if r['serving_format'] else [], lambda r: float(r['price']), FORMAT_LABELS.get)
    if by_format:
        blocks.append(Chart('price-by-format', 'Prix moyen par format', 'bar', [g[0] for g in by_format],
                            [{'name': 'Prix moyen (€)', 'data': [round(g[1], 2) for g in by_format]}],
                            subtitle='Un demi, une pinte et une bouteille ne sont pas comparables : voir aussi le prix au litre'))

    def per_litre(row):
        litres = FORMAT_LITRES.get(row['serving_format'])
        return float(row['price']) / litres if litres else None

    by_venue = _group_average(rows, lambda r: [r['venue_type']] if r['venue_type'] else [], per_litre, VENUE_LABELS.get)
    if by_venue:
        blocks.append(Chart('price-litre-by-venue', 'Prix au litre selon le lieu', 'bar', [g[0] for g in by_venue],
                            [{'name': 'Prix au litre (€)', 'data': [round(g[1], 2) for g in by_venue]}],
                            subtitle='Seulement les dégustations où le format est connu (50, 25, 75 ou 33 cl) : écart de prix bar / maison / événement'))

    by_style = _group_average(rows, lambda r: split_styles(r['beer__style']), lambda r: float(r['price']))[:TOP]
    if by_style:
        blocks.append(Chart('price-by-style', 'Prix moyen par style', 'hbar', [g[0] for g in by_style],
                            [{'name': 'Prix moyen (€)', 'data': [round(g[1], 2) for g in by_style]}],
                            subtitle='Les styles les plus bus avec un prix renseigné ; repère pour fixer le prix d\'un nouveau style'))

    def bucket_of(row):
        value = float(row['price'])
        return next((label for low, high, label in PRICE_BUCKETS if low <= value < high), None)

    by_price = {g[0]: g for g in _group_average(rows, lambda r: [bucket_of(r)], lambda r: r['note'])}
    names = [label for *_x, label in PRICE_BUCKETS if label in by_price]
    if names:
        blocks.append(Chart('price-vs-note', 'Note moyenne selon le prix payé', 'bar', names,
                            [{'name': 'Note moyenne /10', 'data': [round(by_price[n][1], 2) for n in names]}],
                            subtitle='Un verre plus cher est-il mieux noté ? Mesure la valeur perçue'))
    return blocks


def _price_trend(drinks, period):
    rows = (drinks.filter(price__isnull=False).annotate(bucket=period.trunc('date')).values('bucket')
            .annotate(avg=Avg('price'), members=Count('drinker', distinct=True)))
    by_bucket = {(row['bucket'].date() if hasattr(row['bucket'], 'date') else row['bucket']): row for row in rows}
    data = [round(float(by_bucket[b]['avg']), 2) if b in by_bucket and is_publishable(by_bucket[b]['members']) else None for b in period.buckets()]
    if not any(value is not None for value in data):
        return []
    return [Chart('price-trend', 'Évolution du prix moyen payé', 'line', [period.label(b) for b in period.buckets()],
                  [{'name': 'Prix moyen (€)', 'data': data}], subtitle=f'Inflation perçue par les membres ; un point est masqué sous {MIN_GROUP_SIZE} dégustateurs')]


def _format_mix(drinks, period):
    counts = defaultdict(lambda: defaultdict(int))
    for row in drinks.exclude(serving_format='').annotate(bucket=period.trunc('date')).values('bucket', 'serving_format').annotate(n=Count('pk')):
        counts[row['serving_format']][row['bucket'].date() if hasattr(row['bucket'], 'date') else row['bucket']] += row['n']
    if not counts:
        return []
    buckets = period.buckets()
    return [Chart('format-mix', 'Formats servis dans le temps', 'bar', [period.label(b) for b in buckets],
                  [{'name': FORMAT_LABELS.get(fmt, fmt), 'data': [counts[fmt].get(b, 0) for b in buckets]} for fmt in counts],
                  stacked=True, subtitle='Évolution du mix demi / pinte / bouteille / canette')]


def _heatmap(drinks, field, labels, chart_id, title, subtitle):
    """Part de chaque style dans les dégustations d'un contexte (lieu, compagnie, format) ; case à 0 sous MIN_GROUP_SIZE dégustateurs."""
    rows = drinks.exclude(**{field: ''}).values(field, 'beer__style').annotate(n=Count('pk'), members=Count('drinker', distinct=True))
    cells, totals, volume = {}, defaultdict(int), defaultdict(int)
    for row in rows:
        for style in split_styles(row['beer__style']):
            cells[(row[field], style)] = (row['n'], row['members'])
            totals[row[field]] += row['n']
            volume[style] += row['n']
    groups = [key for key in labels if totals.get(key, 0) >= MIN_STYLE_VOLUME]
    styles = [style for style, _ in sorted(volume.items(), key=lambda item: -item[1])[:HEATMAP_STYLES]]
    if not groups or not styles:
        return []
    series = []
    for key in groups:
        data = []
        for style in styles:
            count, members = cells.get((key, style), (0, 0))
            data.append(round(count / totals[key] * 100, 1) if count and is_publishable(members) else 0)
        if any(data):
            series.append({'name': labels[key], 'data': data})
    return [Chart(chart_id, title, 'heatmap', styles, series, subtitle=subtitle)] if series else []


def _venue_weekday(drinks):
    rows = (drinks.exclude(venue_type='').annotate(day=ExtractIsoWeekDay('date')).values('venue_type', 'day')
            .annotate(n=Count('pk'), members=Count('drinker', distinct=True)))
    cells = {(r['venue_type'], r['day']): (r['n'], r['members']) for r in rows}
    venues = [key for key in VENUE_LABELS if any(k[0] == key for k in cells)]
    if not venues:
        return []
    series = [{'name': VENUE_LABELS[v], 'data': [cells[(v, d)][0] if (v, d) in cells and is_publishable(cells[(v, d)][1]) else 0 for d in range(1, 8)]}
              for v in venues]
    series = [row for row in series if any(row['data'])]
    if not series:
        return []
    return [Chart('venue-weekday', 'Quand on boit selon le lieu', 'heatmap', WEEKDAYS, series,
                  subtitle='Dégustations par jour de la semaine et par lieu : bar le week-end, maison en semaine ?')]


def _logging_hour(drinks):
    rows = {r['h']: r['n'] for r in drinks.exclude(created_at__isnull=True).annotate(h=ExtractHour('created_at')).values('h').annotate(n=Count('pk'))}
    if not rows:
        return []
    return [Chart('logging-hour', 'Heure d\'enregistrement des avis', 'bar', [f'{h} h' for h in range(24)],
                  [{'name': 'Avis enregistrés', 'data': [rows.get(h, 0) for h in range(24)]}],
                  subtitle='Heure à laquelle l\'avis est saisi (fuseau de Paris), pas l\'heure où la bière est bue : un repère, pas une mesure exacte')]


def _rating_by(drinks, field, labels, chart_id, title):
    rows = (drinks.exclude(**{field: ''}).exclude(note__isnull=True).values(field)
            .annotate(members=Count('drinker', distinct=True), n=Count('pk'), avg=Avg('note')))
    groups = sorted(((labels.get(row[field], row[field]), round(row['avg'], 2), row['n']) for row in rows if is_publishable(row['members'])),
                    key=lambda group: -group[2])
    if not groups:
        return []
    return [Chart(chart_id, title, 'bar', [g[0] for g in groups], [{'name': 'Note moyenne /10', 'data': [g[1] for g in groups]}])]


def _price_by_zone(drinks, period):
    """Prix moyen par ville (via les lieux où la dégustation a été rattachée) : repère de positionnement local."""
    points = {p.spot_id: p for p in spot_points(period)}
    rows = (BeerSpot.drinks.through.objects.filter(beerspot_id__in=points, drinks_id__in=drinks.filter(price__isnull=False).values('pk'))
            .values_list('beerspot_id', 'drinks__price', 'drinks__drinker'))
    data = [{'zone': points[spot_id].zone, 'price': float(price), 'drinker': drinker} for spot_id, price, drinker in rows]
    by_zone = _group_average(data, lambda r: [r['zone']], lambda r: r['price'])[:TOP]
    if not by_zone:
        return []
    return [Chart('price-by-zone', 'Prix moyen par ville', 'hbar', [g[0] for g in by_zone], [{'name': 'Prix moyen (€)', 'data': [round(g[1], 2) for g in by_zone]}],
                  subtitle=f'Dégustations rattachées à un lieu de la carte ; au moins {MIN_GROUP_SIZE} dégustateurs par ville')]


def build(period, params):
    drinks = Drinks.objects.filter(date__gte=period.start)
    blocks = []

    cover = coverage(drinks)
    if cover:
        blocks.append(Chart('coverage', 'Informations renseignées par dégustation', 'hbar', list(cover),
                            [{'name': '% des dégustations', 'data': [round(v, 1) for v in cover.values()]}],
                            subtitle='Plus ces taux sont hauts, plus les analyses de contexte et de prix sont représentatives. À faire monter dans l\'application.'))

    blocks += context_blocks(drinks, 'ctx')
    blocks += price_blocks(drinks, 'price')
    blocks += price_charts(drinks)
    blocks += _price_by_zone(drinks, period)
    blocks += _price_trend(drinks, period)
    blocks += _format_mix(drinks, period)
    blocks += _heatmap(drinks, 'venue_type', VENUE_LABELS, 'venue-styles', 'Styles bus selon le lieu',
                       'Part de chaque style dans les dégustations d\'un lieu : ce qui se boit au bar vs à la maison')
    blocks += _heatmap(drinks, 'company', COMPANY_LABELS, 'company-styles', 'Styles bus selon la compagnie',
                       'Seul, entre amis, en couple : les styles ne sont pas les mêmes')
    blocks += _heatmap(drinks, 'serving_format', FORMAT_LABELS, 'format-styles', 'Format servi selon le style',
                       'Quels styles se commandent en demi, en pinte ou en bouteille')
    blocks += _venue_weekday(drinks)
    blocks += _rating_by(drinks, 'venue_type', VENUE_LABELS, 'rating-venue', 'Note moyenne selon le lieu')
    blocks += _rating_by(drinks, 'company', COMPANY_LABELS, 'rating-company', 'Note moyenne selon la compagnie')
    blocks += _logging_hour(drinks)

    blocks.append(Note("Lieu, compagnie, format et prix sont facultatifs et déclaratifs. Tant que leur taux de remplissage est bas, "
                       "lisez ces graphiques comme des tendances, pas comme des mesures."))
    return blocks
