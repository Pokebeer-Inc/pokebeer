"""Géographie : où les membres placent leurs lieux, et dans quel contexte (près d'un bar, d'une brasserie, ailleurs).

Confidentialité : les lieux sont regroupés en cases d'environ 11 km et une case n'est affichée que si au moins
MIN_GROUP_SIZE membres distincts y ont des lieux. Aucune coordonnée exacte, aucun pseudo ni titre de lieu n'est exposé.
"""
from collections import defaultdict

from ...models import Bar, Brewery, ReverseGeocode
from . import geo
from .blocks import Chart, Kpi, MapBlock, Note, Table
from .privacy import MIN_GROUP_SIZE, group_publishable, is_publishable
from .spots import spot_points

NEAR_ESTABLISHMENT_M = 150
DENSITY_RADIUS_M = 3_000
DENSE_ZONE = 6  # établissements référencés dans le rayon : au-delà, zone urbaine dense probable
COLORS = {'spot': '#2563eb', 'bar': '#f97316', 'brewery': '#16a34a'}


def establishments():
    """[(lat, lon, 'bar'|'brewery')] pour tous les établissements géolocalisés (données déjà publiques)."""
    places = []
    for kind, model in (('bar', Bar), ('brewery', Brewery)):
        places += [(lat, lon, kind) for lat, lon in
                   model.objects.filter(latitude__isnull=False, longitude__isnull=False).values_list('latitude', 'longitude')]
    return places


def classify_spot(point, places):
    """Contexte d'un lieu : proxy fondé sur les établissements référencés (aucune adresse n'est connue)."""
    nearby = geo.within_m(point, places, NEAR_ESTABLISHMENT_M)
    if nearby:
        return 'Près d\'un bar' if any(p[2] == 'bar' for p in nearby) else 'Près d\'une brasserie'
    around = len(geo.within_m(point, places, DENSITY_RADIUS_M))
    if around == 0:
        return 'Zone sans établissement référencé (rural probable)'
    return 'Zone dense en établissements (urbain probable)' if around >= DENSE_ZONE else 'Zone peu dense (périurbain probable)'


def _geocoded_blocks(resolved):
    """Type de lieu, urbain/rural, villes et régions d'après le géocodage inverse ; groupes trop petits masqués."""
    if not resolved:
        return [Note("Aucun lieu géocodé pour l'instant. Les nouveaux lieux le sont automatiquement à leur enregistrement ; "
                     "pour ceux créés avant cette fonctionnalité, lancez une fois `python manage.py geocode_spots`.")]
    labels = dict(ReverseGeocode.PlaceKind.choices)
    blocks, notes = [], []

    for chart_id, title, label_of in (
        ('real-kind', 'Type de lieu (domicile, bar, extérieur…)', lambda p: labels.get(p.place_kind, 'Autre')),
        ('real-urban', 'Urbain ou rural', lambda p: None if p.is_urban is None else ('Ville' if p.is_urban else 'Village / campagne')),
    ):
        rows, hidden = group_publishable(resolved, label_of)
        if rows:
            blocks.append(Chart(chart_id, title, 'donut', [r[0] for r in rows], [{'name': 'Lieux', 'data': [r[1] for r in rows]}],
                                subtitle='D\'après OpenStreetMap, au point exact du lieu'))
        if hidden:
            notes.append(f'{hidden} lieu(x) de « {title} » masqués (moins de {MIN_GROUP_SIZE} membres par catégorie).')

    cities, _ = group_publishable(resolved, lambda p: p.zone if p.city else None)
    blocks.append(Table('cities', 'Villes les plus actives', ['Ville', 'Lieux', 'Membres'], [list(r) for r in cities[:15]],
                        subtitle=f'Villes avec au moins {MIN_GROUP_SIZE} membres distincts'))
    regions, _ = group_publishable(resolved, lambda p: p.region)
    if regions:
        blocks.append(Chart('regions', 'Lieux par région', 'hbar', [r[0] for r in regions[:12]], [{'name': 'Lieux', 'data': [r[1] for r in regions[:12]]}]))
    blocks += [Note(text) for text in notes]
    return blocks


def build(period, params):
    spots = spot_points(period)
    places = establishments()

    cells = defaultdict(lambda: {'spots': 0, 'members': set()})
    contexts = defaultdict(int)
    for spot in spots:
        cell = cells[spot.cell]
        cell['spots'] += 1
        cell['members'].add(spot.user_id)
        contexts[classify_spot((spot.lat, spot.lon), places)] += 1

    published = {c: v for c, v in cells.items() if is_publishable(len(v['members']))}
    hidden_spots = sum(v['spots'] for c, v in cells.items() if c not in published)

    resolved = [spot for spot in spots if spot.resolved]
    blocks = [
        Kpi('Lieux sur la période', len(spots)),
        Kpi('Lieux géocodés', f'{round(len(resolved) / len(spots) * 100) if spots else 0} %',
            hint='type de lieu, ville et région réels ; automatique à l\'enregistrement d\'un lieu'),
        Kpi('Zones publiées', len(published), hint=f'cases de ~11 km avec au moins {MIN_GROUP_SIZE} membres'),
        Kpi('Lieux dans des zones masquées', hidden_spots, hint='trop peu de membres pour être affichés'),
    ]

    max_spots = max((v['spots'] for v in published.values()), default=1)
    points = []
    for cell, value in published.items():
        lat, lon = geo.cell_center(cell)
        points.append({'lat': lat, 'lng': lon, 'radius': 8 + 22 * value['spots'] / max_spots, 'color': COLORS['spot'],
                       'lines': [f"{value['spots']} lieu(x)", f"{len(value['members'])} membre(s)"]})
    seen = defaultdict(lambda: defaultdict(int))
    for lat, lon, kind in places:
        seen[geo.cell_of(lat, lon)][kind] += 1
    for cell, kinds in seen.items():
        lat, lon = geo.cell_center(cell)
        for kind, label in (('bar', 'bar(s)'), ('brewery', 'brasserie(s)')):
            if kinds[kind]:
                points.append({'lat': lat, 'lng': lon, 'radius': 5 + 2 * kinds[kind], 'color': COLORS[kind],
                               'lines': [f'{kinds[kind]} {label} référencé(s)']})
    blocks.append(MapBlock('geo-map', 'Où sont les membres et les établissements', points,
                           subtitle='Bleu : lieux placés par les membres · orange : bars · vert : brasseries (par case de ~11 km)'))

    blocks += _geocoded_blocks(resolved)

    if contexts:
        ordered = sorted(contexts.items(), key=lambda item: -item[1])
        blocks.append(Chart('spot-context', 'Contexte des lieux placés', 'donut', [c for c, _ in ordered], [{'name': 'Lieux', 'data': [n for _, n in ordered]}],
                            subtitle='Estimation à partir des établissements référencés autour du lieu'))

    zones = sorted(published.items(), key=lambda item: -item[1]['spots'])[:10]
    blocks.append(Table('top-zones', 'Zones les plus actives', ['Zone (lat, lon)', 'Lieux', 'Membres', 'Bars', 'Brasseries'],
                        [[f'{geo.cell_center(c)[0]:.1f}, {geo.cell_center(c)[1]:.1f}', v['spots'], len(v['members']),
                          seen[c]['bar'], seen[c]['brewery']] for c, v in zones],
                        subtitle='Un rapport lieux/établissements élevé signale une zone à fort potentiel peu couverte'))

    blocks.append(Note(
        "Le graphique « Contexte des lieux placés » est une estimation par proximité des établissements référencés, valable pour "
        "tous les lieux. Les blocs « réels » (type de lieu, ville, région) viennent du géocodage inverse mis en cache et ne couvrent "
        "que les lieux déjà géocodés."
    ))
    return blocks
