"""Rapport d'une brasserie : ce qu'un brasseur voudrait savoir de ses clients, comparé à l'ensemble de la communauté.

Cinq sections : vue d'ensemble, bières, audience, visibilité et marché. C'est le produit des gérants (voir access.py et
views/pro_analytics_views.py) et, section après section, la page Établissements de l'administration. Tout est calculé à partir des dégustations
de la brasserie (`Drinks.objects.filter(beer__brewery=…)`) et des briques de la page Consommation. Les chiffres qui reposent sur moins de
MIN_GROUP_SIZE dégustateurs sont masqués ; les repères de comparaison sont des moyennes de la communauté, jamais un autre établissement.
"""
from collections import defaultdict
from functools import cached_property, wraps

from django.db.models import Avg, Count, Exists, OuterRef, Q

from ...domain.styles import split_styles
from ...models import Beer, BeerSpot, BeerUser, Drinks, PageView
from . import forecasts, page_views
from .blocks import Chart, Insight, Kpi, Note, Table
from .formatting import euros, fr
from .privacy import MIN_GROUP_SIZE, is_publishable
from .profiles import (audience_blocks, audience_insights, community_average_price, context_blocks, context_insights, price_blocks,
                       price_insight)
from .reports import PlaceReport, Section
from .series import count_series, growth, month_name, trend_chart
from .spots import spot_points
from .tastes import MIN_RATINGS, MIN_STYLE_VOLUME, style_stats

HIDDEN = f'< {MIN_GROUP_SIZE}'
MIN_DELTA_BASE = 5  # sous ce volume sur la période précédente, un pourcentage d'évolution n'est que du bruit : on ne l'affiche pas


class BreweryContext:
    """Ce que plusieurs sections de la brasserie utilisent : les dégustations (siennes et de la communauté) et leurs totaux, calculés une fois."""

    def __init__(self, brewery, period):
        self.brewery, self.period = brewery, period
        self.community = Drinks.objects.filter(date__gte=period.start)
        self.drinks = self.community.filter(beer__brewery=brewery)

    @cached_property
    def total(self):
        return self.community.count()

    @cached_property
    def own_total(self):
        return self.drinks.count()

    @cached_property
    def members(self):
        return self.drinks.values('drinker').distinct().count()

    @property
    def publishable(self):
        return is_publishable(self.members)

    @cached_property
    def average(self):
        return self.drinks.aggregate(avg=Avg('note'))['avg']

    @cached_property
    def community_average(self):
        return self.community.aggregate(avg=Avg('note'))['avg']

    @cached_property
    def previous(self):
        """Dégustations de la brasserie sur la période précédente de même durée (pour les évolutions)."""
        return Drinks.objects.filter(beer__brewery=self.brewery, date__gte=self.period.previous_start, date__lt=self.period.start)

    @cached_property
    def previous_total(self):
        return self.previous.count()

    @cached_property
    def previous_members(self):
        return self.previous.values('drinker').distinct().count()

    @cached_property
    def ranks(self):
        """Identifiants des brasseries, de la plus bue à la moins bue."""
        return list(self.community.values('beer__brewery').annotate(n=Count('pk')).order_by('-n').values_list('beer__brewery', flat=True))

    @cached_property
    def beer_ids(self):
        return list(Beer.objects.filter(brewery=self.brewery, is_deleted=False).values_list('pk', flat=True))


def needs_audience(build):
    """Section qui n'a de sens (et n'est publiable) qu'avec assez de dégustateurs distincts : sinon une note l'explique."""
    @wraps(build)
    def wrapper(ctx):
        if ctx.publishable:
            return build(ctx)
        return [Note(f"Moins de {MIN_GROUP_SIZE} dégustateurs distincts sur la période : le détail est masqué pour qu'aucun membre ne soit reconnaissable.")]
    return wrapper


def _rating_share(drinks):
    counts = {row['note']: row['n'] for row in drinks.exclude(note__isnull=True).values('note').annotate(n=Count('pk'))}
    total = sum(counts.values())
    return [round(counts.get(note, 0) / total * 100, 1) if total else 0 for note in range(11)], total


def _style_averages(community):
    """{style: note moyenne} sur la communauté (styles ayant au moins MIN_RATINGS notes)."""
    return {style: total / rated for style, (_n, total, rated) in style_stats(community).items() if rated >= MIN_RATINGS}


def _beer_table(drinks, brewery, community):
    averages = _style_averages(community)
    rows = (drinks.values('beer', 'beer__name', 'beer__style')
            .annotate(n=Count('pk'), members=Count('drinker', distinct=True), avg=Avg('note'), avg_price=Avg('price'),
                      priced=Count('drinker', distinct=True, filter=Q(price__isnull=False))).order_by('-n'))
    wishes = dict(Beer.objects.filter(brewery=brewery, is_deleted=False).annotate(w=Count('wishlisted_by')).values_list('pk', 'w'))
    through = BeerUser.wishlist_beers.through
    converted = dict(through.objects.filter(beer__brewery=brewery).filter(
        Exists(Drinks.objects.filter(drinker_id=OuterRef('beeruser_id'), beer_id=OuterRef('beer_id')))).values_list('beer').annotate(n=Count('pk')))
    table = []
    for row in rows:
        shown = is_publishable(row['members'])
        peers = [averages[s] for s in split_styles(row['beer__style']) if s in averages]
        market = sum(peers) / len(peers) if peers else None
        gap = fr(row['avg'] - market, 2, signed=True) if shown and row['avg'] is not None and market is not None else '—'
        table.append([row['beer__name'], row['n'] if shown else HIDDEN, row['members'] if shown else HIDDEN,
                      round(row['avg'], 2) if shown and row['avg'] is not None else '—', gap,
                      euros(float(row['avg_price'])) if row['avg_price'] is not None and is_publishable(row['priced']) else '—',
                      wishes.get(row['beer'], 0), converted.get(row['beer'], 0)])
    return Table('brewery-beers', f'Bières de {brewery.name} : performance', ['Bière', 'Dégustations', 'Dégustateurs', 'Note moyenne', 'Écart au style', 'Prix moyen', 'Souhaits', 'Souhaits goûtés'],
                 table, subtitle='Écart au style : note de la bière moins la note moyenne de son style sur Pokebeer. Souhaits goûtés : membres qui l\'avaient mise en « À goûter » puis l\'ont notée')


def _market_share_by_style(drinks, community):
    own, market = style_stats(drinks), style_stats(community)
    total = community.count()
    rows = []
    for style, (count, _t, _r) in own.items():
        overall = market.get(style, (0,))[0]
        if overall >= MIN_STYLE_VOLUME:
            rows.append([style, count, overall, f'{fr(count / overall * 100, 1)} %'])
    rows.sort(key=lambda row: -row[1])
    return Table('brewery-style-share', 'Part de marché par style', ['Style', 'Dégustations de la brasserie', 'Dégustations du style (tous)', 'Part de marché'], rows[:10],
                 subtitle=f'Styles de la brasserie ayant au moins {MIN_STYLE_VOLUME} dégustations sur Pokebeer ({total} dégustations au total sur la période)')


def _loyalty_counts(drinks):
    """(dégustateurs fidèles, dégustateurs) : fidèle = a noté au moins deux bières différentes de la brasserie (attachement à la marque, pas à une bière).
    None sous le seuil d'anonymat."""
    counts = [row['beers'] for row in drinks.values('drinker').annotate(beers=Count('beer', distinct=True))]
    if not is_publishable(len(counts)):
        return None
    return sum(1 for beers in counts if beers >= 2), len(counts)


def _audience_reach(brewery, drinks, period):
    """Vues de la fiche et de ses bières, évolution, et dégustations obtenues pour 100 visiteurs des fiches bière. Renvoie (blocs, constats)."""
    beer_ids = list(Beer.objects.filter(brewery=brewery, is_deleted=False).values_list('pk', flat=True))
    page = page_views.scoped(period, **{PageView.Kind.BREWERY: [brewery.pk]})
    beers = page_views.scoped(period, **{PageView.Kind.BEER: beer_ids})
    blocks = [*page_views.kpis('fiche', page), *page_views.kpis('bières', beers)]
    insights = []
    views, visitors = page_views.totals(beers)
    if is_publishable(visitors):
        per_hundred = round(drinks.count() / visitors * 100, 1)
        blocks.append(Kpi('Dégustations pour 100 visiteurs', per_hundred,
                          hint='mesure l\'envie de goûter après avoir regardé une de vos fiches bière'))
        insights.append(Insight(f"Vos fiches bière ont reçu {fr(views)} vues ({fr(visitors)} visiteurs) ; cela fait {fr(per_hundred, 1)} dégustations pour 100 visiteurs."))
    blocks.append(page_views.trend('brewery-views-trend', 'Vues de vos fiches', page_views.scoped(
        period, **{PageView.Kind.BREWERY: [brewery.pk], PageView.Kind.BEER: beer_ids}), period))
    return blocks, insights


def _recommendations(brewery, period):
    """Pistes pour une brasserie : styles demandés qu'elle ne propose pas, et ses styles porteurs."""
    now_stats = style_stats(Drinks.objects.filter(date__gte=period.start))
    before_stats = style_stats(Drinks.objects.filter(date__gte=period.previous_start, date__lt=period.start))
    catalog = {s.lower() for beer in brewery.beer_set.filter(is_deleted=False) for s in split_styles(beer.style)}

    gaps, rising = [], []
    for style, (count, total, rated) in now_stats.items():
        average = round(total / rated, 2) if rated >= MIN_RATINGS else None
        change = growth(count, before_stats.get(style, (0,))[0])
        if style.lower() not in catalog and count >= MIN_STYLE_VOLUME:
            gaps.append([style, count, average if average is not None else '—', '—' if change is None else f'{change:+.0f} %'])
        elif style.lower() in catalog and change is not None and change > 0 and count >= MIN_STYLE_VOLUME:
            rising.append([style, count, f'{change:+.0f} %'])
    gaps.sort(key=lambda r: -r[1])
    rising.sort(key=lambda r: -r[1])

    own = defaultdict(int)
    for row in Drinks.objects.filter(beer__brewery=brewery, date__gte=period.start).values('date__month').annotate(n=Count('pk')):
        own[row['date__month']] = row['n']
    return [
        Table('gaps', f'Styles demandés que {brewery.name} ne propose pas', ['Style', 'Dégustations', 'Note moyenne', 'Variation'], gaps[:10],
              subtitle='Piste de nouveauté : forte consommation sur Pokebeer, absent du catalogue de la brasserie'),
        Table('rising', 'Styles du catalogue en hausse', ['Style', 'Dégustations', 'Variation'], rising[:10],
              subtitle='À mettre en avant en priorité'),
        Chart('own-months', f'Dégustations de {brewery.name} par mois', 'bar', [month_name(m) for m in range(1, 13)],
              [{'name': 'Dégustations', 'data': [own[m] for m in range(1, 13)]}], subtitle='Mois porteurs pour planifier lancements et promotions'),
    ]


def _regional_demand(brewery, period):
    """Où les bières de la brasserie sont bues, et où ses styles se boivent sans elle (zones à potentiel).

    Zone = ville si le lieu est géocodé, sinon case de ~11 km ; une zone n'est publiée qu'avec assez de dégustateurs distincts.
    """
    points = {p.spot_id: p for p in spot_points(period)}
    catalog = {s.lower() for beer in brewery.beer_set.filter(is_deleted=False) for s in split_styles(beer.style)}
    rows = BeerSpot.drinks.through.objects.filter(beerspot_id__in=points).values_list(
        'beerspot_id', 'drinks__beer__style', 'drinks__beer__brewery', 'drinks__drinker')

    zones = defaultdict(lambda: {'own': 0, 'own_drinkers': set(), 'style': 0, 'style_drinkers': set()})
    for spot_id, styles, row_brewery_id, drinker in rows:
        zone = zones[points[spot_id].zone]
        if row_brewery_id == brewery.pk:
            zone['own'] += 1
            zone['own_drinkers'].add(drinker)
        elif catalog & {s.lower() for s in split_styles(styles)}:
            zone['style'] += 1
            zone['style_drinkers'].add(drinker)

    where = sorted(([name, z['own'], len(z['own_drinkers'])] for name, z in zones.items() if is_publishable(len(z['own_drinkers']))),
                   key=lambda r: -r[1])
    potential = sorted(([name, z['style'], len(z['style_drinkers'])] for name, z in zones.items()
                        if not z['own'] and is_publishable(len(z['style_drinkers']))), key=lambda r: -r[1])
    return [
        Table('own-zones', f'Où les bières de {brewery.name} sont bues', ['Zone', 'Dégustations', 'Dégustateurs'], where[:10],
              subtitle=f'Dégustations rattachées à un lieu ; au moins {MIN_GROUP_SIZE} dégustateurs par zone'),
        Table('potential-zones', 'Zones à potentiel', ['Zone', 'Dégustations de styles similaires', 'Dégustateurs'], potential[:10],
              subtitle='Zones où l\'on boit déjà les styles de son catalogue (chez d\'autres brasseries), sans aucune de ses bières'),
    ]


def _trend_insight(label, current, previous, months):
    """« Vos dégustations ont progressé de 12 % par rapport aux 12 mois précédents. » ; rien sans période précédente."""
    change = growth(current, previous) if previous >= MIN_DELTA_BASE else None
    if change is None:
        return []
    if abs(change) < 3:
        return [Insight(f"{label} : stable par rapport aux {months} mois précédents.")]
    word, tone = ("ont progressé", "good") if change > 0 else ("ont reculé", "warn")
    return [Insight(f"{label} {word} de {fr(abs(round(change)))} % par rapport aux {months} mois précédents.", tone)]


def _rating_insight(average, community_average):
    if average is None or community_average is None:
        return []
    gap = average - community_average
    if abs(gap) < 0.1:
        return [Insight("Vos bières sont notées comme la moyenne de la communauté.")]
    side, tone = ("au-dessus", "good") if gap > 0 else ("en dessous", "warn")
    return [Insight(f"Vos bières sont notées {fr(abs(gap), 1)} point {side} de la moyenne de la communauté.", tone)]


def _overview(ctx):
    brewery, period = ctx.brewery, ctx.period
    rank = ctx.ranks.index(brewery.pk) + 1 if brewery.pk in ctx.ranks else None
    blocks = [
        Kpi('Dégustations', ctx.own_total, growth(ctx.own_total, ctx.previous_total) if ctx.previous_total >= MIN_DELTA_BASE else None,
            hint=f'n°{rank} sur {len(ctx.ranks)} brasseries' if rank else 'aucune dégustation sur la période'),
        Kpi('Part de marché', f'{fr(ctx.own_total / ctx.total * 100, 1)} %' if ctx.total else '—', hint='des dégustations sur Pokebeer'),
    ]
    if not ctx.publishable:
        return blocks + needs_audience(lambda _ctx: [])(ctx)
    loyalty = _loyalty_counts(ctx.drinks)
    blocks += [
        Kpi('Dégustateurs', ctx.members, growth(ctx.members, ctx.previous_members) if ctx.previous_members >= MIN_DELTA_BASE else None),
        Kpi('Note moyenne', fr(round(ctx.average, 2), 2) if ctx.average is not None else '—',
            hint=f'communauté : {fr(ctx.community_average, 2)}' if ctx.community_average is not None else ''),
    ]
    insights = [*_trend_insight('Vos dégustations', ctx.own_total, ctx.previous_total, period.months), *_rating_insight(ctx.average, ctx.community_average)]
    if loyalty:
        loyal, total = loyalty
        blocks.append(Kpi('Dégustateurs fidèles', f'{fr(round(loyal / total * 100))} %', hint=f'{loyal} sur {total} ont noté au moins 2 de vos bières'))
        if loyal:
            insights.append(Insight(f"{fr(round(loyal / total * 100))} % de vos dégustateurs ont noté au moins deux de vos bières."))
    blocks.append(trend_chart('brewery-trend', 'Dégustations dans le temps', count_series(ctx.drinks, 'date', period), period,
                              unit_name='Dégustations', band=True, subtitle='Avec la tendance prévue (fiable à partir de 6 intervalles complets)'))
    own_ratings, own_n = _rating_share(ctx.drinks)
    community_ratings, _ = _rating_share(ctx.community)
    if own_n:
        blocks.append(Chart('brewery-ratings', 'Répartition des notes', 'bar', [str(n) for n in range(11)],
                            [{'name': 'Vous', 'data': own_ratings}, {'name': 'Communauté', 'data': community_ratings}],
                            subtitle='Part des avis pour chaque note (en %)'))
    return [*insights, *blocks]


def _numeric(value):
    return isinstance(value, (int, float))


def _beer_insights(table):
    """Constats tirés du tableau des bières : la mieux notée, la plus bue, la plus souhaitée (seules les lignes publiables comptent)."""
    rows = [row for row in table.rows if _numeric(row[1])]
    out = []
    rated = [row for row in rows if _numeric(row[3])]
    if rated:
        best = max(rated, key=lambda row: row[3])
        out.append(Insight(f"Votre bière la mieux notée : {best[0]} ({fr(best[3], 1)}/10).", "good"))
    if rows:
        top = max(rows, key=lambda row: row[1])
        out.append(Insight(f"La plus bue : {top[0]} ({top[1]} dégustations)."))
    wished = max(table.rows, key=lambda row: row[6], default=None)
    if wished and wished[6]:
        out.append(Insight(f"{wished[6]} membre(s) ont {wished[0]} dans leur liste « à goûter »."))
    return out


@needs_audience
def _beers(ctx):
    table = _beer_table(ctx.drinks, ctx.brewery, ctx.community)
    return [*_beer_insights(table), table, _market_share_by_style(ctx.drinks, ctx.community)]


@needs_audience
def _audience(ctx):
    insights = [*audience_insights(ctx.drinks, ctx.period.today), *context_insights(ctx.drinks)]
    community_price = community_average_price(ctx.community)
    insights += price_insight(ctx.drinks, community_price)
    return [*insights, *audience_blocks(ctx.drinks, 'brewery-audience', ctx.period.today), *context_blocks(ctx.drinks, 'brewery-ctx'),
            *price_blocks(ctx.drinks, 'brewery-price', community_price)]


def _visibility(ctx):
    blocks, insights = _audience_reach(ctx.brewery, ctx.drinks, ctx.period)
    return [*insights, *blocks]


def _market_insights(gaps, rising, momentum):
    out = []
    if gaps.rows:
        style, count = gaps.rows[0][0], gaps.rows[0][1]
        out.append(Insight(f"Les membres boivent beaucoup de {style} ({count} dégustations) et vous n'en proposez pas : une piste de nouveauté.", "good"))
    if rising.rows:
        out.append(Insight(f"Votre style {rising.rows[0][0]} progresse ({rising.rows[0][2]}) : à mettre en avant."))
    risers = [row[0] for row in momentum.rows if row[-1] == 'En hausse nette']
    if risers:
        out.append(Insight(f"Styles qui montent nettement sur Pokebeer : {', '.join(risers[:3])}.", "good"))
    return out


def _market(ctx):
    gaps, rising, own_months = _recommendations(ctx.brewery, ctx.period)
    own_zones, potential_zones = _regional_demand(ctx.brewery, ctx.period)
    momentum, *momentum_rest = forecasts.style_momentum(ctx.period)
    return [*_market_insights(gaps, rising, momentum), gaps, rising, own_months, own_zones, potential_zones, momentum, *momentum_rest]


class BreweryReport(PlaceReport):
    kind = 'brewery'
    context_class = BreweryContext
    SECTIONS = (
        Section('overview', "Vue d'ensemble", "Vos dégustations, votre part de marché, la fidélité de vos clients et la tendance à venir.", _overview),
        Section('beers', 'Mes bières', "Performance de chaque bière, écart à son style et part de marché par style.", _beers),
        Section('audience', 'Mes clients', "Âge, genre, lieu, compagnie, format et prix payé, comparés à la communauté.", _audience),
        Section('visibility', 'Visibilité', "Vues de vos fiches et envie de goûter qu'elles suscitent.", _visibility),
        Section('market', 'Marché', "Styles demandés que vous ne proposez pas, styles qui montent, zones où vos bières manquent.", _market),
    )
