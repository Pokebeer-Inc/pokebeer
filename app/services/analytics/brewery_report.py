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
from .blocks import Chart, Kpi, Note, Table
from .formatting import euros, fr
from .privacy import MIN_GROUP_SIZE, is_publishable
from .profiles import audience_blocks, community_average_price, context_blocks, price_blocks
from .reports import PlaceReport, Section
from .series import count_series, growth, month_name, trend_chart
from .spots import spot_points
from .tastes import MIN_RATINGS, MIN_STYLE_VOLUME, style_stats

HIDDEN = f'< {MIN_GROUP_SIZE}'


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


def _loyalty(drinks):
    """Part des dégustateurs qui ont noté au moins deux bières différentes de la brasserie : l'attachement à la marque, pas à une bière."""
    per_drinker = drinks.values('drinker').annotate(beers=Count('beer', distinct=True))
    counts = [row['beers'] for row in per_drinker]
    if not is_publishable(len(counts)):
        return []
    loyal = sum(1 for beers in counts if beers >= 2)
    return [Kpi('Dégustateurs fidèles', f'{round(loyal / len(counts) * 100)} %', hint=f'{loyal} sur {len(counts)} ont noté au moins 2 bières de la brasserie')]


def _audience_reach(brewery, drinks, period):
    """Vues de la fiche et de ses bières, évolution, et dégustations obtenues pour 100 visiteurs des fiches bière."""
    beer_ids = list(Beer.objects.filter(brewery=brewery, is_deleted=False).values_list('pk', flat=True))
    page = page_views.scoped(period, **{PageView.Kind.BREWERY: [brewery.pk]})
    beers = page_views.scoped(period, **{PageView.Kind.BEER: beer_ids})
    blocks = [*page_views.kpis('fiche brasserie', page), *page_views.kpis('fiches de ses bières', beers)]
    _views, visitors = page_views.totals(beers)
    if is_publishable(visitors):
        blocks.append(Kpi('Dégustations pour 100 visiteurs', round(drinks.count() / visitors * 100, 1),
                          hint='dégustations de la période rapportées aux visiteurs de ses fiches bière : mesure l\'envie de goûter après avoir regardé'))
    blocks.append(page_views.trend('brewery-views-trend', f'Vues des fiches de {brewery.name}', page_views.scoped(
        period, **{PageView.Kind.BREWERY: [brewery.pk], PageView.Kind.BEER: beer_ids}), period))
    return blocks


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


def _overview(ctx):
    brewery, period = ctx.brewery, ctx.period
    rank = ctx.ranks.index(brewery.pk) + 1 if brewery.pk in ctx.ranks else None
    blocks = [
        Kpi(f'Dégustations de {brewery.name}', ctx.own_total, hint=f'rang {rank} sur {len(ctx.ranks)} brasseries' if rank else 'aucune dégustation sur la période'),
        Kpi('Part des dégustations', f'{fr(ctx.own_total / ctx.total * 100, 1)} %' if ctx.total else '—', hint='part de marché sur Pokebeer'),
    ]
    if not ctx.publishable:
        return blocks + needs_audience(lambda _ctx: [])(ctx)
    blocks += [
        Kpi('Dégustateurs distincts', ctx.members),
        Kpi('Note moyenne', round(ctx.average, 2) if ctx.average is not None else '—',
            hint=f'communauté : {fr(ctx.community_average, 2)}' if ctx.community_average is not None else ''),
        *_loyalty(ctx.drinks),
    ]
    blocks.append(trend_chart('brewery-trend', f'Dégustations de {brewery.name} et prévision', count_series(ctx.drinks, 'date', period), period,
                              unit_name='Dégustations', band=True, subtitle='Tendance, moyenne mobile et fourchette à 80 % (fiable avec 6 intervalles complets ou plus)'))
    own_ratings, own_n = _rating_share(ctx.drinks)
    community_ratings, _ = _rating_share(ctx.community)
    if own_n:
        blocks.append(Chart('brewery-ratings', 'Répartition des notes : brasserie et communauté', 'bar', [str(n) for n in range(11)],
                            [{'name': brewery.name, 'data': own_ratings}, {'name': 'Communauté', 'data': community_ratings}],
                            subtitle='Parts en %. Une brasserie plus à droite que la communauté plaît davantage'))
    return blocks


@needs_audience
def _beers(ctx):
    return [_beer_table(ctx.drinks, ctx.brewery, ctx.community), _market_share_by_style(ctx.drinks, ctx.community)]


@needs_audience
def _audience(ctx):
    return [*audience_blocks(ctx.drinks, 'brewery-audience', ctx.period.today), *context_blocks(ctx.drinks, 'brewery-ctx'),
            *price_blocks(ctx.drinks, 'brewery-price', community_average_price(ctx.community))]


def _visibility(ctx):
    return _audience_reach(ctx.brewery, ctx.drinks, ctx.period)


def _market(ctx):
    return [*_recommendations(ctx.brewery, ctx.period), *_regional_demand(ctx.brewery, ctx.period), *forecasts.style_momentum(ctx.period)]


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
