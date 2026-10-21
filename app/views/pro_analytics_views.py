"""Analytics des gérants : la page d'un établissement (une section à la fois) et le choix de l'établissement quand on en gère plusieurs.

Les droits sont décidés par `services/analytics/access.py` (un gérant lit uniquement ses établissements, l'équipe lit tout) ; les calculs sont ceux
des rapports (brewery_report, bar_report), les mêmes que dans l'administration. Cette vue ne fait que valider la requête et afficher.
"""
import logging
from urllib.parse import urlencode

from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from ..services.analytics import access, export, layout, presentation
from ..services.analytics.periods import MONTH_CHOICES, Period
from ..services.analytics.privacy import MIN_GROUP_SIZE
from ..services.protection.throttle import PRO_ANALYTICS_BY_USER
from .utils import by_user, throttle

__all__ = ['pro_analytics_index', 'pro_analytics_place']

logger = logging.getLogger(__name__)
TOO_MANY = "Trop de consultations, réessayez dans un moment."


def _place_url(kind, place, section=None):
    name = 'pro_analytics_section' if section else 'pro_analytics_place'
    return reverse(name, args=[kind.key, place.slug, *([section] if section else [])])


@never_cache
@require_GET
def pro_analytics_index(request):
    """Établissements dont le membre peut lire les analytics ; un seul : on y va directement."""
    places = access.managed_places(request.user)
    if len(places) == 1:
        return redirect(_place_url(*places[0]))
    return render(request, 'pro_analytics_index.html', {
        'places': [{'kind': kind, 'place': place, 'url': _place_url(kind, place)} for kind, place in places],
        'is_team': access.is_team(request.user),
    })


@never_cache
@require_GET
@throttle(PRO_ANALYTICS_BY_USER, key=by_user, message=TOO_MANY)
def pro_analytics_place(request, kind, slug, section=None):
    """Une section du rapport d'un établissement, avec le choix de la période et l'export CSV de chaque bloc."""
    place_kind, place = access.get_viewable_place(request.user, kind, slug)
    report_class = access.REPORTS[place_kind.key]
    current = report_class.section(section) if section else report_class.SECTIONS[0]
    if current is None:
        raise Http404

    period = Period.from_params(request.GET)  # valeurs validées contre une liste blanche
    blocks = report_class(place, period).blocks(current.key, insights=True)

    target = request.GET.get('export')
    if target:
        logger.info("Export analytics %s/%s/%s par l'utilisateur %s", place_kind.key, place.pk, target, request.user.pk)
        reply = export.response(blocks, target, f'pokebeer-{place_kind.key}-{current.key}-{period.months}m')
        if reply is None:
            raise Http404
        return reply

    insights = [block for block in blocks if block.block_type == 'insight']
    notes, tiles = layout.arrange([block for block in blocks if block.block_type != 'insight'], [], [])
    query = urlencode({'months': period.months})
    here = _place_url(place_kind, place, section)
    return render(request, 'pro_analytics.html', {
        'kind': place_kind, 'place': place, 'section': current, 'period': period,
        'periods': [{'months': m, 'url': f'{here}?{urlencode({"months": m})}', 'active': m == period.months} for m in MONTH_CHOICES],
        'tabs': [{'section': s, 'url': f'{_place_url(place_kind, place, s.key)}?{query}', 'active': s.key == current.key} for s in report_class.SECTIONS],
        'insights': insights, 'notes': notes, 'empty': not tiles, 'empty_text': current.empty_text,
        'menu_url': reverse('bar_menu', args=[place.slug]) if place_kind.key == 'bar' and current.key == 'menu' else '',
        'tiles': [{'block': tile.block, 'table': presentation.present(tile.block) if tile.block.block_type == 'table' else None} for tile in tiles],
        'exportable_ids': {block.id for block in export.exportable(blocks)},
        'query': query, 'detail_url': place_kind.detail_path(place),
        'managed_count': len(access.managed_places(request.user)), 'min_group': MIN_GROUP_SIZE,
    })
