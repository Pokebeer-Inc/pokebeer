"""Catalogue : ce qui est proposé aux membres comparé à ce qu'ils boivent, et la qualité des fiches.

Le rapprochement offre / demande est l'argument central pour un brasseur : quels styles, quelles forces, quelles amertumes sont
demandés sans être assez proposés ?
"""
from collections import defaultdict

from django.db.models import Count, Q, Sum

from .formatting import fr
from ...domain.styles import split_styles
from ...models import Bar, Beer, Brewery, CatalogMiss, Drinks
from ..catalog import style_registry
from .date import date_range
from .blocks import Chart, Kpi, Note, Table
from .tastes import ABV_BUCKETS, IBU_BUCKETS, MIN_STYLE_VOLUME, _bucketed, style_stats

TOP_STYLES = 12
TOP_MISSES = 15
TAIL_BUCKETS = ((0, 0, 'Jamais goûtée'), (1, 1, '1 dégustation'), (2, 5, '2 à 5'), (6, 20, '6 à 20'), (21, 10 ** 9, 'Plus de 20'))


def _percent(part, total):
    return round(part / total * 100, 1) if total else 0


def _completeness(beers, total):
    not_blank = lambda field: beers.exclude(**{f'{field}__isnull': True}).exclude(**{field: ''}).count()  # noqa: E731
    metrics = (
        ('Image', not_blank('image')), ('Description', not_blank('description')), ('Style', not_blank('style')),
        ('Amertume (IBU)', beers.filter(bitterness__isnull=False).count()), ('Degré renseigné', beers.filter(degree__gt=0).count()),
        ('Code-barres (EAN)', beers.filter(ean__isnull=False).count()), ('Vérifiée par l\'équipe', beers.filter(is_verified=True).count()),
    )
    return Chart('beer-completeness', 'Complétude des fiches bière', 'hbar', [name for name, _ in metrics],
                 [{'name': '% des bières', 'data': [_percent(n, total) for _, n in metrics]}],
                 subtitle='Style, degré et IBU alimentent toutes les analyses de goûts : plus ils sont remplis, plus les statistiques sont fiables')


def _supply_vs_demand(beers, drinks):
    """Pour chaque style : part du catalogue (offre) et part des dégustations (demande). Indice > 1 : demande supérieure à l'offre."""
    supply = defaultdict(int)
    for style in beers.values_list('style', flat=True):
        for item in split_styles(style):
            supply[item] += 1
    demand = style_stats(drinks)
    supply_total, demand_total = sum(supply.values()) or 1, sum(v[0] for v in demand.values()) or 1
    ranked = sorted(demand.items(), key=lambda item: -item[1][0])[:TOP_STYLES]
    names = [style for style, _ in ranked]
    chart = Chart('supply-demand', 'Offre et demande par style', 'bar', names,
                  [{'name': 'Part du catalogue (%)', 'data': [round(supply.get(s, 0) / supply_total * 100, 1) for s in names]},
                   {'name': 'Part des dégustations (%)', 'data': [round(demand[s][0] / demand_total * 100, 1) for s in names]}],
                  subtitle='Styles les plus bus : quand la barre de demande dépasse celle de l\'offre, il manque des bières de ce style')
    rows = []
    for style, (count, _total, _rated) in demand.items():
        if count < MIN_STYLE_VOLUME:
            continue
        offer_share, demand_share = supply.get(style, 0) / supply_total * 100, count / demand_total * 100
        rows.append([style, supply.get(style, 0), count, round(demand_share / offer_share, 2) if offer_share else '—'])
    rows.sort(key=lambda r: (0, -r[3]) if r[3] != '—' else (-1, -r[2]))
    table = Table('supply-demand-index', 'Styles sous-représentés dans le catalogue', ['Style', 'Bières au catalogue', 'Dégustations', 'Indice demande / offre'], rows[:TOP_STYLES],
                  subtitle=f'Styles avec au moins {MIN_STYLE_VOLUME} dégustations. Indice > 1 : style plus bu que proposé, créneau pour une brasserie')
    return [chart, table]


def _profile_supply_vs_demand(beers, drinks):
    blocks = []
    for chart_id, title, field, buckets in (('abv-supply', 'Force : offre et demande', 'degree', ABV_BUCKETS), ('ibu-supply', 'Amertume : offre et demande', 'bitterness', IBU_BUCKETS)):
        supply_rows = beers.values(field).annotate(n=Count('pk'))
        labels, supply = _bucketed(supply_rows, buckets, field)
        _labels, demand = _bucketed(drinks.values(f'beer__{field}').annotate(n=Count('pk')), buckets, f'beer__{field}')
        s_total, d_total = sum(supply) or 1, sum(demand) or 1
        blocks.append(Chart(chart_id, title, 'bar', labels,
                            [{'name': 'Part du catalogue (%)', 'data': [round(n / s_total * 100, 1) for n in supply]},
                             {'name': 'Part des dégustations (%)', 'data': [round(n / d_total * 100, 1) for n in demand]}],
                            subtitle='Une tranche très demandée et peu proposée est un créneau de lancement'))
    return blocks


def _long_tail(beers, drinks):
    per_beer = dict(drinks.values_list('beer').annotate(n=Count('pk')))
    counts = [per_beer.get(pk, 0) for pk in beers.values_list('pk', flat=True)]
    data = [sum(1 for n in counts if low <= n <= high) for low, high, _ in TAIL_BUCKETS]
    top = sorted(counts, reverse=True)[:10]
    total = sum(counts)
    blocks = [Chart('beer-tail', 'Dégustations par bière (longue traîne)', 'donut', [label for *_x, label in TAIL_BUCKETS], [{'name': 'Bières', 'data': data}],
                    subtitle='Beaucoup de bières jamais goûtées : le catalogue est large mais peu exploré, ou les bières sont mal mises en avant')]
    if total:
        blocks.insert(0, Kpi('Part des 10 bières les plus bues', f'{fr(_percent(sum(top), total))} %', hint='concentration des dégustations : très haute = quelques hits écrasent le reste'))
    return blocks


def _regions():
    blocks = []
    for model, chart_id, title in ((Brewery, 'breweries-by-department', 'Brasseries par département'), (Bar, 'bars-by-department', 'Bars par département')):
        counts = defaultdict(int)
        for code in model.objects.exclude(postal_code='').values_list('postal_code', flat=True):
            counts[code[:2]] += 1
        ranked = sorted(counts.items(), key=lambda item: -item[1])[:15]
        if ranked:
            blocks.append(Chart(chart_id, title, 'hbar', [f'Dép. {code}' for code, _ in ranked], [{'name': 'Fiches', 'data': [n for _, n in ranked]}],
                                subtitle='Deux premiers chiffres du code postal : où le référencement est dense ou absent'))
    return blocks


def _unrecognized_styles(beers):
    """Styles saisis qui ne figurent pas au référentiel : à ajouter (ou à rattacher comme alias) dans l'administration, « Styles de bière »."""
    counts = defaultdict(int)
    for style in beers.exclude(style__isnull=True).exclude(style='').values_list('style', flat=True):
        for item in split_styles(style):
            if not style_registry.recognized(item):
                counts[item] += 1
    rows = sorted(([style, n] for style, n in counts.items()), key=lambda row: (-row[1], row[0]))[:20]
    return Table('style-unrecognized', 'Styles hors référentiel', ['Style', 'Bières'], rows,
                 subtitle=f'{len(counts)} style(s) à rattacher au référentiel (Administration, Styles de bière) pour que les comparaisons restent fiables')


def _families(beers, drinks):
    """Offre et demande par famille de styles : lecture d'ensemble, utile quand les styles sont nombreux et peu fournis."""
    supply = {row['style_family']: row['n'] for row in beers.exclude(style_family='').values('style_family').annotate(n=Count('pk'))}
    demand = {row['beer__style_family']: row['n'] for row in drinks.exclude(beer__style_family='').values('beer__style_family').annotate(n=Count('pk'))}
    names = sorted(set(supply) | set(demand), key=lambda name: -demand.get(name, 0))
    if not names:
        return []
    supply_total, demand_total = sum(supply.values()) or 1, sum(demand.values()) or 1
    return [Chart('family-supply-demand', 'Offre et demande par famille de styles', 'bar', names,
                  [{'name': 'Part du catalogue (%)', 'data': [round(supply.get(n, 0) / supply_total * 100, 1) for n in names]},
                   {'name': 'Part des dégustations (%)', 'data': [round(demand.get(n, 0) / demand_total * 100, 1) for n in names]}],
                  subtitle='Familles du référentiel de styles ; les bières au style hors référentiel n\'y figurent pas')]


def _misses(period):
    """Ce que les membres ont cherché sans le trouver : termes de recherche, codes-barres inconnus, étiquettes non reconnues (compteurs, sans membre)."""
    rows = date_range(CatalogMiss.objects.all(), 'day', period.start)
    labels = dict(CatalogMiss.Source.choices)
    by_source = list(rows.values('source').annotate(n=Sum('count')).order_by('-n'))
    if not by_source:
        return [Note("Aucune demande sans résultat enregistrée sur la période (la mesure compte les recherches vides, les codes-barres inconnus et les étiquettes non reconnues).")]
    top = rows.exclude(key='').values('source', 'key').annotate(n=Sum('count')).order_by('-n')[:TOP_MISSES]
    return [
        Chart('miss-sources', 'Demandes sans résultat par origine', 'donut', [labels[r['source']] for r in by_source], [{'name': 'Demandes', 'data': [r['n'] for r in by_source]}],
              subtitle='Demande non satisfaite du catalogue : chaque barre est une bière ou un lieu que des membres voulaient trouver'),
        Table('miss-terms', 'Termes et codes les plus demandés sans résultat', ['Origine', 'Terme ou code', 'Demandes'],
              [[labels[r['source']], r['key'], r['n']] for r in top],
              subtitle='Liste de bières à ajouter en priorité. Compteurs seulement : aucune demande n\'est reliée à un membre'),
    ]


def build(period, params):
    beers = Beer.objects.filter(is_deleted=False)
    total = beers.count()
    drinks = Drinks.objects.filter(date__gte=period.start)
    distinct_styles = {s.lower() for style in beers.values_list('style', flat=True) for s in split_styles(style)}
    blocks = [
        Kpi('Bières au catalogue', total),
        Kpi('Bières vérifiées', f'{fr(_percent(beers.filter(is_verified=True).count(), total))} %'),
        Kpi('Styles distincts', len(distinct_styles), hint='nom officiel du référentiel ou saisie libre : voir « Styles hors référentiel »'),
        Kpi('Bières sans style', beers.filter(Q(style__isnull=True) | Q(style='')).count(), hint='invisibles dans toutes les analyses par style'),
        _completeness(beers, total),
        *_supply_vs_demand(beers, drinks),
        *_profile_supply_vs_demand(beers, drinks),
        *_long_tail(beers, drinks),
        *_regions(),
        *_families(beers, drinks),
        _unrecognized_styles(beers),
        *_misses(period),
        Note("Les bières n'ont pas de date de création : on ne peut pas encore mesurer le rythme d'enrichissement du catalogue autrement que par la première dégustation."),
    ]
    return blocks
