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

COLORS = {'spot': '#2563eb', 'bar': '#f97316', 'brewery': '#16a34a'}


def establishments():
    """[(lat, lon, 'bar'|'brewery')] pour tous les établissements géolocalisés (données déjà publiques)."""
    places = []
    for kind, model in (('bar', Bar), ('brewery', Brewery)):
        places += [(lat, lon, kind) for lat, lon in
                   model.objects.filter(latitude__isnull=False, longitude__isnull=False).values_list('latitude', 'longitude')]
    return places


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
    for spot in spots:
        cell = cells[spot.cell]
        cell['spots'] += 1
        cell['members'].add(spot.user_id)

    published = {c: v for c, v in cells.items() if is_publishable(len(v['members']))}
    hidden_spots = sum(v['spots'] for c, v in cells.items() if c not in published)

    resolved = [spot for spot in spots if spot.resolved]
    blocks = [Kpi('Lieux sur la période', len(spots))]

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

    geocoded = round(len(resolved) / len(spots) * 100) if spots else 0
    blocks.append(Note(
        f"Couverture et anonymat : {geocoded} % des lieux sont géocodés (les blocs « type de lieu », ville et région ne couvrent qu'eux ; "
        f"automatique à l'enregistrement d'un lieu, sinon `manage.py geocode_spots`). {len(published)} zone(s) de ~11 km sont publiées "
        f"(au moins {MIN_GROUP_SIZE} membres) ; {hidden_spots} lieu(x) sont dans des zones masquées, faute de membres assez nombreux."
    ))
    return blocks
