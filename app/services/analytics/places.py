"""Établissements et aide à la décision : classement, et pistes de mise en avant pour une brasserie donnée."""
from collections import defaultdict

from django.db.models import Avg, Count

from ...models import BeerSpot, Brewery, Drinks
from .blocks import Chart, Kpi, Note, Table
from .geography import establishments
from .privacy import MIN_GROUP_SIZE, is_publishable
from .spots import spot_points
from .series import growth, month_name
from .tastes import MIN_RATINGS, MIN_STYLE_VOLUME, split_styles, style_stats

TOP = 15


def _leaderboard(period):
    current = {r['beer_id__brewery_id']: r for r in
               Drinks.objects.filter(date__gte=period.start).values('beer_id__brewery_id', 'beer_id__brewery_id__name')
               .annotate(n=Count('pk'), avg=Avg('note'), beers=Count('beer_id', distinct=True))}
    before = {r['beer_id__brewery_id']: r['n'] for r in
              Drinks.objects.filter(date__gte=period.previous_start, date__lt=period.start)
              .values('beer_id__brewery_id').annotate(n=Count('pk'))}
    rows = sorted(current.values(), key=lambda r: -r['n'])[:TOP]
    return Table('breweries', 'Brasseries les plus bues', ['Brasserie', 'Dégustations', 'Bières bues', 'Note moyenne', 'Variation'],
                 [[r['beer_id__brewery_id__name'], r['n'], r['beers'], round(r['avg'], 2) if r['avg'] is not None else '—',
                   '—' if growth(r['n'], before.get(r['beer_id__brewery_id'], 0)) is None
                   else f"{growth(r['n'], before.get(r['beer_id__brewery_id'], 0)):+.0f} %"] for r in rows],
                 subtitle='Variation par rapport à la période précédente de même durée')


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
    for row in Drinks.objects.filter(beer_id__brewery_id=brewery, date__gte=period.start).values('date__month').annotate(n=Count('pk')):
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
        'beerspot_id', 'drinks__beer_id__style', 'drinks__beer_id__brewery_id', 'drinks__drinker_id')

    zones = defaultdict(lambda: {'own': 0, 'own_drinkers': set(), 'style': 0, 'style_drinkers': set()})
    for spot_id, styles, brewery_id, drinker in rows:
        zone = zones[points[spot_id].zone]
        if brewery_id == brewery.pk:
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


def build(period, params):
    blocks = [Kpi('Établissements géolocalisés', len(establishments())), _leaderboard(period)]

    slug = params.get('brewery', '')
    brewery = Brewery.objects.filter(slug=slug).first() if slug else None
    if brewery:
        blocks += _recommendations(brewery, period) + _regional_demand(brewery, period)
    else:
        blocks.append(Note("Choisissez une brasserie ci-dessus pour obtenir des pistes de mise en avant."))
    return blocks
