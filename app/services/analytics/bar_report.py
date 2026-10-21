"""Rapport d'un bar : ce que les membres boivent et paient autour de lui, quand, avec qui, et ce qui se vend ailleurs.

Un lieu est « au bar » s'il est à moins de NEAR_BAR_M d'un bar référencé. Les détails d'un bar ne sont affichés que si au moins MIN_GROUP_SIZE
membres distincts sont concernés (k-anonymat) : sinon, un client pourrait être reconnu. Cinq sections : vue d'ensemble, ce qui se boit, clientèle,
visibilité et marché ; voir reports.py pour le principe et access.py pour qui peut les lire.
"""
from collections import Counter, defaultdict
from functools import cached_property, wraps

from django.db.models import Count
from django.db.models.functions import ExtractIsoWeekDay, ExtractMonth

from ...domain.styles import split_styles
from ...models import BeerSpot, Drinks, PageView
from . import consumption, forecasts, geo, page_views
from .blocks import Chart, Insight, Kpi, Note, Table
from .formatting import fr
from .date import date_range
from .habits import WEEKDAYS
from .privacy import MIN_GROUP_SIZE, is_publishable
from .profiles import (audience_blocks, audience_insights, community_average_price, context_blocks, context_insights, price_blocks,
                       price_insight)
from .reports import PlaceReport, Section
from .series import month_name
from .spots import spot_points
from .tastes import MIN_STYLE_VOLUME

NEAR_BAR_M = 150
HIDDEN = f'< {MIN_GROUP_SIZE}'
TOP = 10


def spots_near(bar, points):
    """Lieux (SpotPoint) à moins de NEAR_BAR_M du bar ; aucun si le bar n'est pas localisé."""
    if bar.latitude is None or bar.longitude is None:
        return []
    return [p for _, _, p in geo.within_m((bar.latitude, bar.longitude), [(p.lat, p.lon, p) for p in points], NEAR_BAR_M)]


def _tastings(spot_ids):
    """Dégustations rattachées aux lieux donnés (style, bière, note, dégustateur)."""
    return list(
        BeerSpot.drinks.through.objects.filter(beerspot_id__in=spot_ids)
        .values_list('drinks__beer__style', 'drinks__beer__name', 'drinks__note', 'drinks__drinker')
    )


class BarContext:
    """Lieux autour du bar et dégustations qui leur sont rattachées, calculés une fois pour toutes les sections."""

    def __init__(self, bar, period):
        self.bar, self.period = bar, period

    @cached_property
    def near(self):
        return spots_near(self.bar, spot_points(self.period))

    @cached_property
    def members(self):
        return len({p.user_id for p in self.near})

    @property
    def publishable(self):
        return is_publishable(self.members)

    @cached_property
    def spot_ids(self):
        return [p.spot_id for p in self.near]

    @cached_property
    def tastings(self):
        return _tastings(self.spot_ids)

    @cached_property
    def drinks(self):
        return Drinks.objects.filter(pk__in=BeerSpot.drinks.through.objects.filter(beerspot_id__in=self.spot_ids).values('drinks_id'))

    @cached_property
    def community(self):
        return Drinks.objects.filter(date__gte=self.period.start)


def needs_activity(build):
    """Section qui n'a de sens qu'avec assez de membres distincts autour du bar : sinon une note explique pourquoi elle est vide."""
    @wraps(build)
    def wrapper(ctx):
        if ctx.publishable:
            return build(ctx)
        if ctx.bar.latitude is None or ctx.bar.longitude is None:
            return [Note(f"{ctx.bar.name} n'est pas localisé : ajoutez son adresse pour que l'activité autour du bar soit mesurée.")]
        return [Note(f"Pas assez d'activité autour de {ctx.bar.name} pour afficher un détail anonyme (au moins {MIN_GROUP_SIZE} membres distincts requis).")]
    return wrapper


def _style_mix(tastings, period):
    """Styles bus autour du bar comparés à la consommation globale : un indice > 1 = style sur-représenté ici."""
    local = Counter(style for styles, *_ in tastings for style in split_styles(styles))
    drinkers = defaultdict(set)
    for styles, _name, _note, drinker in tastings:
        for style in split_styles(styles):
            drinkers[style].add(drinker)

    overall = Counter()
    for row in date_range(Drinks.objects.all(), 'date', period.start).values('beer__style').annotate(n=Count('pk')):
        for style in split_styles(row['beer__style']):
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


def _visit_profile(ctx):
    """Taille du groupe et bières par visite."""
    spots = BeerSpot.objects.filter(pk__in=ctx.spot_ids)
    group_sizes = [friends + 1 for friends in spots.annotate(f=Count('friends')).values_list('f', flat=True)]
    blocks = [Kpi('Taille moyenne du groupe', round(sum(group_sizes) / len(group_sizes), 1), hint='membre + amis indiqués sur le lieu')]
    if ctx.spot_ids:
        blocks.append(Kpi('Bières par visite', round(ctx.drinks.count() / len(ctx.spot_ids), 1), hint='dégustations rattachées / lieux placés'))
    return blocks


def _rhythm_insights(charts):
    """Jour et mois les plus fréquentés, d'après les graphiques de rythme."""
    out = []
    for chart, names, template in ((charts[0], WEEKDAYS, "Le jour le plus fréquenté autour de votre bar : {name} ({n} lieux)."),
                                   (charts[1], [month_name(m) for m in range(1, 13)], "Le mois le plus fréquenté : {name} ({n} lieux).")):
        data = chart.series[0]['data']
        if data and max(data):
            out.append(Insight(template.format(name=names[data.index(max(data))].lower(), n=max(data))))
    return out


@needs_activity
def _overview(ctx):
    rhythm = _rhythm(ctx.spot_ids)
    insights = [Insight(f"{ctx.members} membres différents ont placé un lieu à moins de {NEAR_BAR_M} m de votre bar ({len(ctx.near)} lieux au total)."),
                *_rhythm_insights(rhythm)]
    return [*insights, Kpi('Lieux autour du bar', len(ctx.near)), Kpi('Membres distincts', ctx.members), *_visit_profile(ctx), *rhythm]


def _drink_insights(style_table, beer_table):
    out = []
    over = [row for row in style_table.rows if isinstance(row[-1], (int, float)) and row[-1] > 1.2]
    if over:
        best = max(over, key=lambda row: row[-1])
        out.append(Insight(f"{best[0]} est sur-représenté chez vous (x{fr(best[-1], 1)} par rapport à la moyenne) : à mettre en avant.", "good"))
    if beer_table.rows:
        out.append(Insight(f"La bière la plus bue autour de votre bar : {beer_table.rows[0][0]}."))
    return out


@needs_activity
def _drinks(ctx):
    styles, beers = _style_mix(ctx.tastings, ctx.period), _top_beers(ctx.tastings)
    return [*_drink_insights(styles, beers), styles, beers]


@needs_activity
def _customers(ctx):
    community_price = community_average_price(ctx.community)
    insights = [*audience_insights(ctx.drinks, ctx.period.today), *context_insights(ctx.drinks), *price_insight(ctx.drinks, community_price)]
    return [*insights, *context_blocks(ctx.drinks, 'bar-ctx'), *price_blocks(ctx.drinks, 'bar-price', community_price),
            *audience_blocks(ctx.drinks, 'bar-audience', ctx.period.today)]


def _visibility(ctx):
    scoped = page_views.scoped(ctx.period, **{PageView.Kind.BAR: [ctx.bar.pk]})
    views, visitors = page_views.totals(scoped)
    insights = [Insight(f"Votre fiche a été consultée {fr(views)} fois par {fr(visitors)} visiteurs sur la période.")] if is_publishable(visitors) else []
    return [*insights, *page_views.kpis('fiche', scoped), page_views.trend('bar-views-trend', 'Vues de votre fiche', scoped, ctx.period)]


def _market(ctx):
    """Repères de la communauté, sans rapport avec le bar lui-même : quels styles montent, et les prix pratiqués."""
    momentum, *rest = forecasts.style_momentum(ctx.period)
    risers = [row[0] for row in momentum.rows if row[-1] == 'En hausse nette']
    insights = [Insight(f"Styles qui montent nettement sur Pokebeer : {', '.join(risers[:3])}.", "good")] if risers else []
    return [*insights, momentum, *rest, *consumption.price_charts(ctx.community)]


class BarReport(PlaceReport):
    kind = 'bar'
    context_class = BarContext
    SECTIONS = (
        Section('overview', "Vue d'ensemble", "Activité autour du bar, taille des groupes, jours et mois les plus fréquentés.", _overview),
        Section('drinks', 'Ce qu\'on boit', "Styles sur-représentés autour du bar et bières les plus bues.", _drinks),
        Section('customers', 'Clientèle', "Âge, genre, compagnie, format et prix payé, comparés à la communauté.", _customers),
        Section('visibility', 'Visibilité', "Vues de la fiche du bar.", _visibility),
        Section('market', 'Marché', "Styles qui montent et prix pratiqués par la communauté.", _market),
    )
