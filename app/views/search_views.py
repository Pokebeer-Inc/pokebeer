"""Recherche unique : une barre, des onglets (Bières, Brasseries, Bars, Près de moi, Membres).

La page complète et l'API de rafraîchissement (saisie en direct) produisent le même bloc de résultats par le même code :
`build_results`. Sans JavaScript, la page fonctionne par simples liens et envoi du formulaire.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from ..forms import DrinkForm
from ..models import Beer, Drinks
from ..services import place_directory, place_filters, search
from ..services.places import BAR, BREWERY, with_targets
from .services.selectors import (
    get_filtered_bars, get_filtered_beers, get_filtered_breweries, get_filtered_users, search_query,
)

PAGE = 10        # éléments d'un onglet avant « Charger plus »
TABS = (('bieres', "Bières"), ('brasseries', "Brasseries"), ('bars', "Bars"), ('proche', "Près de moi"), ('membres', "Membres"))
TAB_KEYS = {key for key, _ in TABS}
FILTER_PARAMS = ('degree', 'ibu', 'style', 'sort')  # filtres propres à l'onglet Bières
PLACE_TABS = {'brasseries': BREWERY, 'bars': BAR}  # onglets d'établissements et leur type


def active_tab(request):
    """Onglet demandé ; `uq` (ancien paramètre de la recherche de membres) ouvre l'onglet Membres."""
    tab = request.GET.get('tab')
    if tab in TAB_KEYS:
        return tab
    return 'membres' if request.GET.get('uq') else 'bieres'


def beer_styles():
    """Styles du catalogue pour le filtre (un champ peut en contenir plusieurs, séparés par des virgules)."""
    raw = Beer.objects.filter(is_deleted=False).exclude(style__isnull=True).exclude(style='').values_list('style', flat=True).distinct()
    return sorted({style.strip() for value in raw for style in value.split(',') if style.strip()})


def _beer_context(request, beers):
    ids = [beer.id for beer in beers]
    return {
        'beers': beers,
        'rating_form': DrinkForm(),
        'rated_beer_ids': list(Drinks.objects.filter(drinker_id=request.user, beer_id__in=ids).values_list('beer_id', flat=True)),
        'wishlist_beer_ids': list(request.user.wishlist_beers.filter(id__in=ids).values_list('id', flat=True)),
    }


def _filter_context(request, tab):
    """Panneau de filtres de l'onglet : gabarit, valeurs proposées et état (les filtres appartiennent à l'onglet affiché)."""
    if tab == 'bieres':
        return {
            'filter_template': 'partials/beer_filters_panel.html', 'styles': beer_styles(),
            'filtered': any(request.GET.get(param) for param in FILTER_PARAMS),
        }
    if tab in PLACE_TABS:
        kind = PLACE_TABS[tab]
        return {
            'filter_template': 'partials/place_filters.html', 'cities': place_filters.cities(kind.model),
            'styles': beer_styles() if kind is BREWERY else [], 'is_brewery_tab': kind is BREWERY,
            'filtered': place_filters.is_filtered(request.GET),
        }
    return {}


def build_results(request):
    """Contexte du bloc de résultats : onglets, et le contenu de l'onglet actif (une seule requête pour l'onglet affiché)."""
    tab, query = active_tab(request), search_query(request)
    context = {'tabs': TABS, 'active_tab': tab, 'query': query, 'has_query': bool(search.terms(query))}
    sections = {
        'bieres': ('beers', get_filtered_beers),
        'brasseries': ('breweries', get_filtered_breweries),
        'bars': ('bars', get_filtered_bars),
        'membres': ('users', get_filtered_users),
    }
    if tab == 'proche':
        # Rien à chercher côté serveur : la page publie l'annuaire et le navigateur classe par distance (la position reste sur l'appareil)
        context['nearby'] = True
        return context
    name, getter = sections[tab]
    context[name] = list(getter(request)[:PAGE])
    context['page_full'] = len(context[name]) == PAGE
    for name, kind in (('breweries', BREWERY), ('bars', BAR)):
        if name in context:
            context[name] = with_targets(context[name], kind)
    if context.get('beers'):
        context.update(_beer_context(request, context['beers']))
    context.update(_filter_context(request, tab))
    return context


@login_required(login_url='login')
def all_beers_view(request):
    """Page de recherche : barre unique, onglets et résultats."""
    return render(request, 'all_beers.html', build_results(request))


@login_required(login_url='login')
@require_GET
@cache_control(private=True, max_age=300)
def places_directory(request):
    """Bars et brasseries localisés (données publiques des fiches) : la page « Près de moi » les classe selon la position de l'appareil."""
    return JsonResponse({'places': place_directory.directory()})


@login_required(login_url='login')
@require_GET
def search_api(request):
    """Bloc de résultats seul (saisie en direct, changement d'onglet ou de filtre)."""
    return JsonResponse({'html': render_to_string('partials/search_results.html', build_results(request), request=request)})
