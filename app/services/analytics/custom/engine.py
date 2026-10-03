"""Exécution d'une tuile personnalisée : même sortie (blocs Kpi/Chart/Table) que les pages prédéfinies.

Les requêtes sont construites exclusivement à partir du catalogue ; la définition est revalidée à chaque affichage
(une ligne modifiée en base ne peut pas contourner le catalogue). Les regroupements non temporels n'affichent que des
groupes d'au moins MIN_GROUP_SIZE membres distincts (k-anonymat).
"""
from django.db.models import Count

from ..blocks import Chart, Kpi, Table
from ..date import date_range
from ..privacy import MIN_GROUP_SIZE
from ..series import trend_chart
from .catalog import CATALOG
from .spec import SpecError, validate


def _scoped_queryset(dataset, period, filters):
    queryset = dataset.queryset()
    if dataset.date_field:
        queryset = date_range(queryset, dataset.date_field, period.start)
    brewery = (filters or {}).get('brewery')
    if brewery and dataset.brewery_path:
        queryset = queryset.filter(**{dataset.brewery_path: brewery})
    return queryset


def _as_date(value):
    return value.date() if hasattr(value, 'date') else value


def _round(value, decimals):
    return round(value, decimals) if value is not None and decimals else (value or 0)


def _grouped_rows(dataset, dimension, spec, period, queryset):
    """[(libellé, [valeurs par mesure])] dans l'ordre d'affichage, et True si des groupes ont été masqués."""
    aggregates = {key: dataset.measures[key].aggregate(dataset) for key in spec.measures}
    grouped = queryset.annotate(dim=dimension.expression(period, dataset)).values('dim').annotate(**aggregates)

    suppress = dimension.kind == 'category' and dataset.member_field is not None
    if suppress:
        grouped = grouped.annotate(_members=Count(dataset.member_field, distinct=True))
        hidden = grouped.filter(_members__lt=MIN_GROUP_SIZE).exists()
        grouped = grouped.filter(_members__gte=MIN_GROUP_SIZE)
    else:
        hidden = False

    def values(row):
        return [_round(row[key], dataset.measures[key].decimals) for key in spec.measures]

    if dimension.kind == 'category':
        first = spec.measures[0]
        ordering = ('dim',) if spec.sort == 'label_asc' else (f'-{first}', 'dim')
        return [(dimension.to_label(row['dim']), values(row)) for row in grouped.order_by(*ordering)[:spec.limit]], hidden

    by_value = {(_as_date(row['dim']) if dimension.kind == 'time' else row['dim']): values(row) for row in grouped}
    empty = [0] * len(spec.measures)
    rows = []
    for category in dimension.categories(period):
        label = period.label(category) if dimension.kind == 'time' else dimension.to_label(category)
        rows.append((label, by_value.get(category, empty)))
    return rows, hidden


def build_block(tile_pk, title, raw_spec, period, filters=None):
    """Bloc d'affichage d'une tuile ; une définition devenue invalide donne un tableau d'erreur, jamais une exception."""
    block_id = f'tile-{tile_pk}'
    try:
        spec = validate(raw_spec)
    except SpecError as error:
        return _with_ids(Table(block_id, title, ['Tuile invalide'], [[str(error)]]), tile_pk)

    dataset = CATALOG[spec.dataset]
    queryset = _scoped_queryset(dataset, period, filters)
    measure_labels = [dataset.measures[key].label for key in spec.measures]

    if spec.chart == 'kpi':
        measure = dataset.measures[spec.measures[0]]
        value = queryset.aggregate(value=measure.aggregate(dataset))['value']
        kpi = Kpi(title, _round(value, measure.decimals), hint=f'{dataset.label} · {measure.label}')
        return _with_ids(kpi, tile_pk)

    dimension = dataset.dimensions[spec.dimension]
    rows, hidden = _grouped_rows(dataset, dimension, spec, period, queryset)
    subtitle = f'{dataset.label} · par {dimension.label.lower()}'
    if hidden:
        subtitle += f' · groupes de moins de {MIN_GROUP_SIZE} membres masqués'

    if spec.chart == 'table':
        block = Table(block_id, title, [dimension.label, *measure_labels], [[label, *values] for label, values in rows], subtitle=subtitle)
    elif spec.chart == 'line' and spec.trend:
        block = trend_chart(block_id, title, [values[0] for _, values in rows], period, subtitle=subtitle, unit_name=measure_labels[0])
    else:
        categories = [label for label, _ in rows]
        series = [{'name': name, 'data': [values[index] for _, values in rows]} for index, name in enumerate(measure_labels)]
        block = Chart(block_id, title, spec.chart, categories, series, subtitle=subtitle)
    return _with_ids(block, tile_pk)


def _with_ids(block, tile_pk):
    block.id = f'tile-{tile_pk}'
    block.tile_pk = tile_pk  # permet à l'interface de proposer modifier/supprimer
    return block
