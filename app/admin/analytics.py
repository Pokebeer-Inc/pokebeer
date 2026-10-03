"""Pages d'analytics (staff uniquement) : une vue générique qui affiche les blocs construits par services/analytics."""
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.views.decorators.http import require_GET, require_POST

import json
import logging

from ..models import Bar, Brewery
from ..services.analytics import export, layout
from ..services.analytics.periods import GRANULARITIES, MONTH_CHOICES, Period
from ..services.analytics.registry import PAGES, PAGES_BY_KEY


logger = logging.getLogger(__name__)

# Sélecteurs d'entité des pages : paramètre GET -> (modèle, libellé). Seul le slug sert de clé de recherche.
PICKERS = {'brewery': (Brewery, 'Brasserie'), 'bar': (Bar, 'Bar')}


def _check_staff(request):
    user = request.user
    if not (user.is_active and (user.is_staff or user.is_superuser)):
        raise PermissionDenied


def analytics_index(request):
    return redirect('admin_analytics', key=PAGES[0].key)


def analytics_page(request, key):
    _check_staff(request)
    page = PAGES_BY_KEY.get(key)
    if page is None:
        raise Http404

    period = Period.from_params(request.GET)
    params = {name: request.GET.get(name, '')[:150] for name in PICKERS}
    blocks = page.build(period, params)
    notes, tiles = layout.arrange(blocks, *layout.load(request.user, page.key))

    export_target = request.GET.get('export')
    if export_target:
        return _export(request, page, period, blocks, export_target)

    # Filtres courants, réutilisés tels quels par les liens d'export
    query = request.GET.copy()
    query.pop('export', None)

    context = {
        **admin.site.each_context(request),
        'title': page.title,
        'page': page,
        'pages': PAGES,
        'period': period,
        'month_choices': MONTH_CHOICES,
        'granularities': [(k, label) for k, (label, _) in GRANULARITIES.items()],
        'pickers': [{'param': name, 'label': PICKERS[name][1], 'selected': params[name],
                     'options': PICKERS[name][0].objects.order_by('name').values('slug', 'name')} for name in page.pickers],
        'query': query.urlencode(),
        'exportable_ids': {block.id for block in export.exportable(blocks)},
        'blocks': blocks,
        'notes': notes,
        'tiles': tiles,
        'has_map': any(block.block_type == 'map' for block in blocks),
    }
    return TemplateResponse(request, 'admin/analytics/page.html', context)


def _export(request, page, period, blocks, target):
    """CSV d'un bloc (ou ZIP de tous) avec les filtres appliqués à la page ; mêmes droits que la page."""
    logger.info("Export analytics %s/%s par l'utilisateur %s", page.key, target, request.user.pk)
    suffix = f'{period.months}m' if page.period else 'all'
    if target == 'all':
        content, content_type, extension = export.to_zip(blocks), 'application/zip', 'zip'
        name = f'pokebeer-{page.key}-{suffix}'
    else:
        block = next((b for b in export.exportable(blocks) if b.id == target), None)
        if block is None:
            raise Http404
        content, content_type, extension = export.to_csv(block), 'text/csv; charset=utf-8', 'csv'
        name = f'pokebeer-{page.key}-{export.safe_name(block.id)}-{suffix}'
    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{name}.{extension}"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


MAX_LAYOUT_BODY = 8_192


def analytics_layout(request, key):
    """Mémorise la disposition de l'utilisateur connecté pour cette page (jamais celle d'un autre : aucun identifiant de membre accepté)."""
    _check_staff(request)
    if key not in PAGES_BY_KEY:
        raise Http404
    if len(request.body) > MAX_LAYOUT_BODY:
        return JsonResponse({'ok': False, 'error': 'Requête trop volumineuse'}, status=413)
    try:
        data = json.loads(request.body)
        order, hidden = layout.clean_ids(data.get('order')), layout.clean_ids(data.get('hidden'))
    except (ValueError, AttributeError):
        order = hidden = None
    if order is None or hidden is None:
        return JsonResponse({'ok': False, 'error': 'Disposition invalide'}, status=400)
    layout.save(request.user, key, order, hidden)
    return JsonResponse({'ok': True})


# `admin_view` impose la connexion à l'admin (et la redirige vers sa page de login) ; GET uniquement : aucune écriture.
urlpatterns = [
    path('', admin.site.admin_view(require_GET(analytics_index)), name='admin_analytics_index'),
    path('<slug:key>/layout/', admin.site.admin_view(require_POST(analytics_layout)), name='admin_analytics_layout'),
    path('<slug:key>/', admin.site.admin_view(require_GET(analytics_page)), name='admin_analytics'),
]
