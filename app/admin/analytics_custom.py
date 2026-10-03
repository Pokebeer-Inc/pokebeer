"""Vues personnalisées d'analytics : créer ses vues et ses tuiles, les modifier, les supprimer.

Toutes les vues sont réservées au staff ; chaque vue personnalisée n'est accessible qu'à son propriétaire (404 sinon,
pour ne pas révéler l'existence de celles des autres). Les modifications se font en POST uniquement, avec CSRF.
"""
from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.views.decorators.http import require_POST

from ..models import AnalyticsTile, AnalyticsView
from ..services.analytics.custom import service
from ..services.analytics.custom.catalog import CATALOG
from ..services.analytics.custom.forms import TileForm, ViewNameForm
from ..services.analytics.custom.spec import CHART_TYPES, SpecError
from ..services.analytics.registry import PAGES
from .analytics import _check_staff, render_page


def _owned_view(request, view_id):
    _check_staff(request)
    return get_object_or_404(AnalyticsView, pk=view_id, user=request.user)


def _catalog_for_builder():
    """Ce dont le formulaire a besoin pour n'afficher que les choix compatibles (libellés seulement, aucune donnée)."""
    return {
        key: {
            'label': dataset.label,
            'dimensions': [{'key': k, 'label': d.label, 'kind': d.kind} for k, d in dataset.dimensions.items()],
            'measures': [{'key': k, 'label': m.label} for k, m in dataset.measures.items()],
        }
        for key, dataset in CATALOG.items()
    }


def _context(request, **extra):
    return {
        **admin.site.each_context(request),
        'pages': PAGES,
        'custom_views': AnalyticsView.objects.filter(user=request.user),
        'max_views': service.MAX_VIEWS,
        **extra,
    }


def custom_home(request):
    """Liste des vues de l'administrateur et création d'une nouvelle vue."""
    _check_staff(request)
    return TemplateResponse(request, 'admin/analytics/custom_home.html', _context(request, title='Custom', form=ViewNameForm()))


@require_POST
def view_create(request):
    _check_staff(request)
    form = ViewNameForm(request.POST)
    if form.is_valid():
        try:
            view = service.create_view(request.user, form.cleaned_data['name'])
            messages.success(request, f"Vue « {view.name} » créée. Ajoutez votre première tuile.")
            return redirect('admin_analytics_tile_new', view_id=view.pk)
        except SpecError as error:
            form.add_error('name', str(error))
    return TemplateResponse(request, 'admin/analytics/custom_home.html', _context(request, title='Custom', form=form), status=400)


def view_show(request, view_id):
    view = _owned_view(request, view_id)
    page = service.build_page(view)
    return render_page(request, page, {'custom_view': view, **_context(request)})


@require_POST
def view_rename(request, view_id):
    view = _owned_view(request, view_id)
    try:
        service.rename_view(view, request.POST.get('name', ''))
        messages.success(request, "Vue renommée.")
    except SpecError as error:
        messages.error(request, str(error))
    return redirect('admin_analytics_view', view_id=view.pk)


@require_POST
def view_delete(request, view_id):
    view = _owned_view(request, view_id)
    name = view.name
    service.delete_view(view)
    messages.success(request, f"Vue « {name} » supprimée.")
    return redirect('admin_analytics_custom')


def _tile_form_response(request, view, form, tile=None, status=200):
    context = _context(
        request, title='Nouvelle tuile' if tile is None else 'Modifier la tuile', form=form, custom_view=view, tile=tile,
        catalog=_catalog_for_builder(), chart_types=CHART_TYPES,
    )
    return TemplateResponse(request, 'admin/analytics/tile_form.html', context, status=status)


def tile_new(request, view_id):
    view = _owned_view(request, view_id)
    form = TileForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            service.add_tile(view, form.cleaned_data['title'], form.cleaned_data['spec'])
            messages.success(request, "Tuile ajoutée.")
            return redirect('admin_analytics_view', view_id=view.pk)
        except SpecError as error:
            form.add_error(None, str(error))
    return _tile_form_response(request, view, form, status=400 if request.method == 'POST' else 200)


def tile_edit(request, view_id, tile_id):
    view = _owned_view(request, view_id)
    tile = get_object_or_404(AnalyticsTile, pk=tile_id, view=view)
    form = TileForm(request.POST) if request.method == 'POST' else TileForm.from_tile(tile)
    if request.method == 'POST' and form.is_valid():
        service.update_tile(tile, form.cleaned_data['title'], form.cleaned_data['spec'])
        messages.success(request, "Tuile modifiée.")
        return redirect('admin_analytics_view', view_id=view.pk)
    return _tile_form_response(request, view, form, tile=tile, status=400 if request.method == 'POST' else 200)


@require_POST
def tile_delete(request, view_id, tile_id):
    view = _owned_view(request, view_id)
    get_object_or_404(AnalyticsTile, pk=tile_id, view=view).delete()
    messages.success(request, "Tuile supprimée.")
    return redirect('admin_analytics_view', view_id=view.pk)
