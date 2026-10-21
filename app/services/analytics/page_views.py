"""Vues des fiches pour les analytics : totaux, courbes et classements à partir des compteurs journaliers (voir services/tracking/page_views.py).

« Visiteurs » est la somme des visiteurs distincts de chaque jour : un même membre revenu trois jours compte trois fois. Un total de visiteurs
sous le seuil d'anonymat est masqué comme tout autre petit groupe.
"""
from django.db.models import Q, Sum

from ...models import Bar, Beer, Brewery, PageView
from .blocks import Kpi, Table
from .date import date_range
from .privacy import MIN_GROUP_SIZE, is_publishable
from .series import count_series, trend_chart

HIDDEN = f'< {MIN_GROUP_SIZE}'
KIND_MODELS = {PageView.Kind.BEER: Beer, PageView.Kind.BREWERY: Brewery, PageView.Kind.BAR: Bar}
TOP = 15


def scoped(period, **targets):
    """Compteurs de la période pour des fiches données : `scoped(period, brewery=[3], beer=[1, 2])`."""
    condition = Q()
    for kind, ids in targets.items():
        condition |= Q(kind=kind, object_id__in=list(ids))
    return date_range(PageView.objects.filter(condition), 'day', period.start)


def totals(queryset):
    """(vues, visiteurs) d'un ensemble de compteurs."""
    result = queryset.aggregate(views=Sum('views'), visitors=Sum('visitors'))
    return result['views'] or 0, result['visitors'] or 0


def kpis(label, queryset):
    """Deux KPI (vues, visiteurs). Sous le seuil d'anonymat les deux sont masqués : avec un seul visiteur, les vues le désigneraient."""
    views, visitors = totals(queryset)
    shown = is_publishable(visitors)
    return [Kpi(f'Vues · {label}', views if shown else HIDDEN, hint='consultations de la fiche (équipe et gérants exclus)'),
            Kpi(f'Visiteurs · {label}', visitors if shown else HIDDEN, hint='somme des visiteurs distincts de chaque jour')]


def trend(chart_id, title, queryset, period):
    """Vues dans le temps avec prévision."""
    return trend_chart(chart_id, title, count_series(queryset, 'day', period, Sum('views')), period, unit_name='Vues', band=True)


def by_object(period, kind):
    """{identifiant: (vues, visiteurs)} de toutes les fiches d'un type sur la période."""
    rows = date_range(PageView.objects.filter(kind=kind), 'day', period.start).values('object_id').annotate(views=Sum('views'), visitors=Sum('visitors'))
    return {row['object_id']: (row['views'], row['visitors']) for row in rows}


def top_table(period, kind, table_id, title):
    """Fiches d'un type les plus vues, avec leur nom."""
    ranked = sorted(by_object(period, kind).items(), key=lambda item: -item[1][0])[:TOP]
    names = dict(KIND_MODELS[kind].objects.filter(pk__in=[pk for pk, _ in ranked]).values_list('pk', 'name'))
    rows = [[names.get(pk, '(supprimée)'), views if is_publishable(visitors) else HIDDEN, visitors if is_publishable(visitors) else HIDDEN]
            for pk, (views, visitors) in ranked]
    return Table(table_id, title, ['Fiche', 'Vues', 'Visiteurs'], rows,
                 subtitle='Équipe et gérants de la fiche exclus ; visiteurs distincts par jour, additionnés sur la période')
