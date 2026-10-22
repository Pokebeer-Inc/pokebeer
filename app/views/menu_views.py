"""Carte d'un bar : page de gestion, recherche d'une bière du catalogue, ajout, modification et retrait d'une ligne.

Les droits (gérants du bar et équipe) sont décidés par `services/establishments/menu.py` ; un membre qui ne peut pas gérer la carte reçoit un 404,
comme si le bar n'existait pas. Les vues valident les formulaires et répondent ; les règles (doublons, limite) sont dans le service.
"""
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from ..forms import MenuEntryForm
from ..models import Bar, BarBeer, Beer
from ..services.catalog import permissions
from ..services.establishments import menu
from ..services.protection.throttle import AUTOCOMPLETE_BY_USER, MENU_EDITS_BY_USER
from .utils import TOO_MANY_SEARCHES, by_user, throttle

__all__ = ['bar_menu_view', 'bar_menu_search', 'bar_menu_add', 'bar_menu_update', 'bar_menu_remove']

TOO_MANY_EDITS = "Trop de modifications, réessayez dans un moment."


def _managed_bar(request, bar_slug):
    bar = get_object_or_404(Bar, slug=bar_slug)
    if not menu.can_manage(request.user, bar):
        raise Http404
    return bar


def _back(bar):
    return redirect('bar_menu', bar_slug=bar.slug)


@never_cache
@require_GET
def bar_menu_view(request, bar_slug):
    """Page de gestion de la carte : recherche pour ajouter, puis une ligne par bière (prix, format, retrait)."""
    bar = _managed_bar(request, bar_slug)
    entries = list(menu.entries(bar))
    return render(request, 'bar_menu.html', {
        'bar': bar, 'entries': entries, 'max_entries': menu.MAX_ACTIVE_ENTRIES,
        'formats': BarBeer._meta.get_field('serving_format').choices,
    })


@require_GET
@throttle(AUTOCOMPLETE_BY_USER, key=by_user, json=True, message=TOO_MANY_SEARCHES)
def bar_menu_search(request, bar_slug):
    """Bières du catalogue proches de la saisie, avec « déjà à la carte » (JSON : le navigateur construit la liste avec textContent)."""
    bar = _managed_bar(request, bar_slug)
    found = menu.candidates(request.user, bar, request.GET.get('term', ''))
    return JsonResponse([{'slug': item['beer'].slug, 'name': item['beer'].name, 'brewery': item['beer'].brewery_label,
                          'style': item['beer'].style or '', 'on_menu': item['on_menu']} for item in found], safe=False)


@require_POST
@throttle(MENU_EDITS_BY_USER, key=by_user, message=TOO_MANY_EDITS)
def bar_menu_add(request, bar_slug):
    """Ajoute une bière du catalogue à la carte (prix et format facultatifs)."""
    bar = _managed_bar(request, bar_slug)
    beer = get_object_or_404(Beer.objects.select_related('brewery'), slug=request.POST.get('beer', ''))
    if not permissions.can_view(request.user, beer):
        raise Http404
    form = MenuEntryForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Prix ou format invalide.")
        return _back(bar)
    try:
        _entry, created = menu.add(bar, beer, request.user, form.cleaned_data['price'], form.cleaned_data['serving_format'])
    except menu.MenuError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"« {beer.name} » est à la carte." if created else f"« {beer.name} » était déjà à la carte : ligne mise à jour.")
    return _back(bar)


def _entry(bar, entry_id):
    return get_object_or_404(BarBeer.objects.active().select_related('beer'), pk=entry_id, bar=bar)


@require_POST
@throttle(MENU_EDITS_BY_USER, key=by_user, message=TOO_MANY_EDITS)
def bar_menu_update(request, bar_slug, entry_id):
    """Change le prix et le format d'une ligne (vider un champ l'efface)."""
    bar = _managed_bar(request, bar_slug)
    entry = _entry(bar, entry_id)
    form = MenuEntryForm(request.POST, instance=entry)
    if form.is_valid():
        menu.update(entry, form.cleaned_data['price'], form.cleaned_data['serving_format'])
        messages.success(request, f"« {entry.beer.name} » mise à jour.")
    else:
        messages.error(request, "Prix ou format invalide.")
    return _back(bar)


@require_POST
@throttle(MENU_EDITS_BY_USER, key=by_user, message=TOO_MANY_EDITS)
def bar_menu_remove(request, bar_slug, entry_id):
    bar = _managed_bar(request, bar_slug)
    entry = _entry(bar, entry_id)
    menu.remove(entry)
    messages.success(request, f"« {entry.beer.name} » est retirée de la carte.")
    return _back(bar)
