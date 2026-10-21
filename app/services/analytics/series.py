"""Séries temporelles : agrégation alignée sur la période, moyenne mobile, tendance et prévision indicative."""
from datetime import datetime

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

    La première valeur renvoyée est celle de l'intervalle en cours, les suivantes celles des intervalles à venir.

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


def forecast_band(values, horizon=FORECAST_HORIZON, z=1.28):
    """(bas, haut) autour de `forecast` : intervalle de prédiction de la régression (80 % avec z = 1,28), qui s'élargit avec l'horizon.

    Renvoie ([], []) sous les mêmes conditions que `forecast`. L'écart type des résidus mesure à quel point la série s'écarte de sa droite :
    une série très irrégulière donne une fourchette large, donc une prévision à ne pas surinterpréter."""
    complete = values[:-1]
    trend = linear_trend(complete)
    if not trend:
        return [], []
    slope, intercept = trend
    count = len(complete)
    mean_x = (count - 1) / 2
    spread_x = sum((x - mean_x) ** 2 for x in range(count))
    residuals = [y - (intercept + slope * x) for x, y in enumerate(complete)]
    sigma = (sum(r * r for r in residuals) / max(1, count - 2)) ** 0.5
    low, high = [], []
    for step in range(horizon):
        x = count + step
        margin = z * sigma * (1 + 1 / count + (x - mean_x) ** 2 / spread_x) ** 0.5
        centre = intercept + slope * x
        low.append(max(0, round(centre - margin, 2)))
        high.append(max(0, round(centre + margin, 2)))
    return low, high


def trend_strength(values):
    """R² de la tendance linéaire (0 à 1) : part de la variation expliquée par la droite. None s'il y a trop peu de points."""
    trend = linear_trend(values)
    if not trend:
        return None
    slope, intercept = trend
    mean_y = sum(values) / len(values)
    total = sum((y - mean_y) ** 2 for y in values)
    if not total:
        return 0.0
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in enumerate(values))
    return round(1 - residual / total, 2)


def growth(current, previous):
    """Variation en % ; None quand la période précédente est vide (variation non définie)."""
    return None if not previous else round((current - previous) / previous * 100, 1)


def _forecast_line(values, projected):
    """Série de prévision alignée sur les intervalles : part du dernier intervalle complet (courbe continue), puis couvre l'intervalle en cours
    (la première valeur prévue) et les suivants."""
    return [None] * (len(values) - 2) + [values[-2]] + projected


def trend_chart(chart_id, title, values, period, subtitle="", unit_name="Valeur", band=False):
    """Graphique d'une série avec sa moyenne mobile et sa prévision (en pointillés), et en option sa fourchette à 80 %.

    La première valeur prévue est celle de l'intervalle en cours (le dernier, incomplet, est exclu de la tendance) : elle s'affiche à sa place,
    les autres prolongent le graphique d'autant d'intervalles futurs."""
    buckets = period.buckets()
    labels = [period.label(bucket) for bucket in buckets]
    predicted = forecast(values)
    future, bucket = [], buckets[-1]
    for _ in predicted[1:]:
        bucket = period.next_bucket(bucket)
        future.append(period.label(bucket))
    padding = [None] * len(future)

    series = [
        {'name': unit_name, 'data': values + padding},
        {'name': f'Moyenne mobile ({MOVING_AVERAGE_WINDOW})', 'data': moving_average(values) + padding},
    ]
    dashed, shaded = [], None
    if predicted:
        series.append({'name': 'Prévision (indicative)', 'data': _forecast_line(values, predicted)})
        dashed = [2]
        if band:
            for name, bound in zip(('Fourchette basse (80 %)', 'Fourchette haute (80 %)'), forecast_band(values), strict=True):
                series.append({'name': name, 'data': _forecast_line(values, bound)})
                dashed.append(len(series) - 1)
            shaded = (len(series) - 2, len(series) - 1)
    return Chart(chart_id, title, 'line', labels + future, series, subtitle=subtitle, dashed=dashed, band=shaded)


def month_name(number):
    return ['Janv.', 'Févr.', 'Mars', 'Avr.', 'Mai', 'Juin', 'Juil.', 'Août', 'Sept.', 'Oct.', 'Nov.', 'Déc.'][number - 1]
