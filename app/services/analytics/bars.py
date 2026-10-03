"""Bars : activité des membres autour de chaque bar et pistes de mise en avant.

Un lieu est « au bar » s'il est à moins de NEAR_BAR_M d'un bar référencé. Les détails d'un bar ne sont affichés que si au
moins MIN_GROUP_SIZE membres distincts sont concernés (k-anonymat) : sinon, un client pourrait être reconnu.
"""
from collections import Counter, defaultdict

from django.db.models.functions import ExtractIsoWeekDay, ExtractMonth
from django.db.models import Count

from ...models import Bar, BeerSpot, Drinks
from . import geo
from .blocks import Chart, Kpi, Note, Table
from .date import date_range
from .habits import WEEKDAYS
from .privacy import MIN_GROUP_SIZE, is_publishable
from .series import month_name
from .spots import spot_points
from .tastes import MIN_STYLE_VOLUME, split_styles

NEAR_BAR_M = 150
HIDDEN = f'< {MIN_GROUP_SIZE}'
TOP = 10


def _spots_near(bar, points):
    return [p for _, _, p in geo.within_m((bar.latitude, bar.longitude), [(p.lat, p.lon, p) for p in points], NEAR_BAR_M)]


def _tastings(spot_ids):
    """Dégustations rattachées aux lieux donnés (style, bière, note, dégustateur)."""
    return list(
        BeerSpot.drinks.through.objects.filter(beerspot_id__in=spot_ids)
        .values_list('drinks__beer_id__style', 'drinks__beer_id__name', 'drinks__note', 'drinks__drinker_id')
    )


def _overview(bars, points):
    rows = []
    for bar in bars:
        near = _spots_near(bar, points)
        members = len({p.user_id for p in near})
        rows.append((bar.name, len(near), members))
    rows.sort(key=lambda r: -r[1])
    return Table('bars-overview', 'Activité autour de chaque bar', ['Bar', 'Lieux à proximité', 'Membres'],
                 [[name, spots if is_publishable(members) else HIDDEN, members if is_publishable(members) else HIDDEN]
                  for name, spots, members in rows[:25]],
                 subtitle=f'Lieux placés à moins de {NEAR_BAR_M} m du bar ; en dessous de {MIN_GROUP_SIZE} membres, les chiffres sont masqués')


def _style_mix(tastings, period):
    """Styles bus autour du bar comparés à la consommation globale : un indice > 1 = style sur-représenté ici."""
    local = Counter(style for styles, *_ in tastings for style in split_styles(styles))
    drinkers = defaultdict(set)
    for styles, _name, _note, drinker in tastings:
        for style in split_styles(styles):
            drinkers[style].add(drinker)

    overall = Counter()
    for row in date_range(Drinks.objects.all(), 'date', period.start).values('beer_id__style').annotate(n=Count('pk')):
        for style in split_styles(row['beer_id__style']):
            overall[style] += row['n']
    local_total, overall_total = sum(local.values()) or 1, sum(overall.values()) or 1

    rows = []
    for style, count in local.most_common():
        if count < MIN_STYLE_VOLUME // 2 or not is_publishable(len(drinkers[style])):
            continue
        share, global_share = count / local_total * 100, overall.get(style, 0) / overall_total * 100
        rows.append([style, count, f'{share:.0f} %', f'{global_share:.0f} %', round(share / global_share, 2) if global_share else '—'])
    return Table('bar-styles', 'Styles bus autour du bar', ['Style', 'Dégustations', 'Part ici', 'Part globale', 'Indice'], rows[:TOP],
                 subtitle="Indice > 1 : style sur-représenté autour de ce bar, donc à mettre en avant en priorité")


def _top_beers(tastings):
    drinkers, notes = defaultdict(set), defaultdict(list)
    for _style, name, note, drinker in tastings:
        drinkers[name].add(drinker)
        if note is not None:
            notes[name].append(note)
    rows = [[name, len(d), round(sum(notes[name]) / len(notes[name]), 2) if notes[name] else '—'] for name, d in drinkers.items() if is_publishable(len(d))]
    rows.sort(key=lambda r: -r[1])
    return Table('bar-beers', 'Bières les plus bues autour du bar', ['Bière', 'Dégustateurs', 'Note moyenne'], rows[:TOP],
                 subtitle=f'Au moins {MIN_GROUP_SIZE} dégustateurs distincts par bière')


def _rhythm(spot_ids):
    queryset = BeerSpot.objects.filter(pk__in=spot_ids)
    weekday = {r['d']: r['n'] for r in queryset.annotate(d=ExtractIsoWeekDay('date')).values('d').annotate(n=Count('pk'))}
    month = {r['m']: r['n'] for r in queryset.annotate(m=ExtractMonth('date')).values('m').annotate(n=Count('pk'))}
    return [
        Chart('bar-weekday', 'Fréquentation par jour de la semaine', 'bar', WEEKDAYS,
              [{'name': 'Lieux', 'data': [weekday.get(i, 0) for i in range(1, 8)]}]),
        Chart('bar-month', 'Fréquentation par mois', 'bar', [month_name(m) for m in range(1, 13)],
              [{'name': 'Lieux', 'data': [month.get(m, 0) for m in range(1, 13)]}]),
    ]


def build(period, params):
    bars = list(Bar.objects.filter(latitude__isnull=False, longitude__isnull=False).order_by('name'))
    points = spot_points(period)
    blocks = [Kpi('Bars géolocalisés', len(bars)), _overview(bars, points)]

    bar = next((b for b in bars if b.slug == params.get('bar')), None)
    if not bar:
        blocks.append(Note("Choisissez un bar ci-dessus pour voir ce que les membres boivent autour de lui."))
        return blocks

    near = _spots_near(bar, points)
    members = len({p.user_id for p in near})
    if not is_publishable(members):
        blocks.append(Note(f"Pas assez d'activité autour de {bar.name} pour afficher un détail anonyme "
                           f"(au moins {MIN_GROUP_SIZE} membres distincts requis)."))
        return blocks

    spot_ids = [p.spot_id for p in near]
    blocks += [Kpi(f'Lieux autour de {bar.name}', len(near)), Kpi('Membres distincts', members)]
    tastings = _tastings(spot_ids)
    blocks += [_style_mix(tastings, period), _top_beers(tastings), *_rhythm(spot_ids)]
    return blocks
