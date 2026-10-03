"""Séries temporelles : agrégation alignée sur la période, moyenne mobile, tendance et prévision indicative."""
from datetime import date, datetime

from django.db.models import Count

from .blocks import Chart
from .date import date_range

MIN_POINTS_FOR_FORECAST = 6
FORECAST_HORIZON = 4
MOVING_AVERAGE_WINDOW = 3


def _as_date(value):
    return value.date() if isinstance(value, datetime) else value


def count_series(queryset, field_name, period, aggregate=None):
    """Valeur par intervalle (zéro quand il n'y a rien), alignée sur `period.buckets()`."""
    rows = (
        date_range(queryset, field_name, period.start)
        .annotate(bucket=period.trunc(field_name)).values('bucket')
        .annotate(value=aggregate or Count('pk')).order_by('bucket')
    )
    by_bucket = {_as_date(row['bucket']): row['value'] for row in rows}
    return [by_bucket.get(bucket, 0) for bucket in period.buckets()]


def moving_average(values, window=MOVING_AVERAGE_WINDOW):
    result = []
    for index in range(len(values)):
        chunk = values[max(0, index - window + 1): index + 1]
        result.append(round(sum(chunk) / len(chunk), 2))
    return result


def linear_trend(values):
    """(pente, ordonnée) de la régression linéaire par moindres carrés ; None s'il y a trop peu de points."""
    count = len(values)
    if count < MIN_POINTS_FOR_FORECAST:
        return None
    mean_x, mean_y = (count - 1) / 2, sum(values) / count
    variance = sum((x - mean_x) ** 2 for x in range(count))
    slope = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(values)) / variance
    return slope, mean_y - slope * mean_x


def forecast(values, horizon=FORECAST_HORIZON):
    """Prolongation de la tendance linéaire, sans le dernier point (intervalle en cours, donc incomplet).

    Volontairement simple et remplaçable : une vraie saisonnalité (Holt-Winters, Prophet) demande au moins
    deux cycles complets d'historique. Renvoie [] tant que l'historique est insuffisant.
    """
    complete = values[:-1]
    trend = linear_trend(complete)
    if not trend:
        return []
    slope, intercept = trend
    start = len(complete)
    return [max(0, round(intercept + slope * (start + step), 2)) for step in range(horizon)]


def growth(current, previous):
    """Variation en % ; None quand la période précédente est vide (variation non définie)."""
    return None if not previous else round((current - previous) / previous * 100, 1)


def trend_chart(chart_id, title, values, period, subtitle="", unit_name="Valeur"):
    """Graphique d'une série avec sa moyenne mobile et sa prévision (en pointillés)."""
    labels = [period.label(bucket) for bucket in period.buckets()]
    predicted = forecast(values)
    future, bucket = [], period.buckets()[-1]
    for _ in predicted:
        bucket = period.next_bucket(bucket)
        future.append(period.label(bucket))

    series = [
        {'name': unit_name, 'data': values + [None] * len(predicted)},
        {'name': f'Moyenne mobile ({MOVING_AVERAGE_WINDOW})', 'data': moving_average(values) + [None] * len(predicted)},
    ]
    dashed = []
    if predicted:
        # La prévision part du dernier point complet pour que la courbe soit continue
        anchor = len(values) - 2
        forecast_data = [None] * len(values) + predicted
        forecast_data[anchor] = values[anchor]
        series.append({'name': 'Prévision (indicative)', 'data': forecast_data})
        dashed = [2]
    return Chart(chart_id, title, 'line', labels + future, series, subtitle=subtitle, dashed=dashed)


def month_name(number):
    return ['Janv.', 'Févr.', 'Mars', 'Avr.', 'Mai', 'Juin', 'Juil.', 'Août', 'Sept.', 'Oct.', 'Nov.', 'Déc.'][number - 1]
