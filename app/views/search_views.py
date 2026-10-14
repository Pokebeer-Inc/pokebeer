"""Recherche unique : une barre, des onglets (Bières, Brasseries, Bars, Près de moi, Membres).

La page complète et l'API de rafraîchissement (saisie en direct) produisent le même bloc de résultats par le même code :
`build_results`. Sans JavaScript, la page fonctionne par simples liens et envoi du formulaire.
"""
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.cache import cache_control
from django.views.decorators.gzip import gzip_page
from django.views.decorators.http import require_GET

from ..services.establishments import place_directory, place_filters
from ..services.catalog import search
from ..services.catalog.styles import catalog_styles
from ..services.establishments.places import BAR, BREWERY, with_targets
from ..services.catalog.selectors import get_filtered_bars, get_filtered_beers, get_filtered_breweries, get_filtered_users, search_query
from .utils import beer_list_context, chosen_tab

PAGE = 10        # éléments d'un onglet avant « Charger plus »
PREVIEW = 3      # éléments de chaque rubrique dans l'onglet « Tout »
TABS = (('all', "Tout"), ('beers', "Bières"), ('bars', "Bars"), ('breweries', "Brasseries"), ('members', "Membres"))
TAB_KEYS = {key for key, _ in TABS} | {'nearby'}  # « Près de moi » n'est plus une puce : on y arrive par « Autour de vous"
FILTER_PARAMS = ('degree', 'ibu', 'style', 'sort')  # filtres propres à l'onglet Bières
PLACE_TABS = {'breweries': BREWERY, 'bars': BAR}  # onglets d'établissements et leur type


# Anciens noms français des onglets (adresses déjà enregistrées ou envoyées)
LEGACY_TABS = {'tout': 'all', 'bieres': 'beers', 'brasseries': 'breweries', 'membres': 'members', 'proche': 'nearby'}


def normalize_tab(value):
    """Nom de l'onglet en anglais, que la demande utilise le nom actuel ou un ancien nom français."""
    return LEGACY_TABS.get(value, value)


def active_tab(request, default='beers'):
    """Onglet demandé ; `uq` (ancien paramètre de la recherche de membres) ouvre l'onglet Members."""
    return chosen_tab(request.GET.get('tab'), TAB_KEYS, LEGACY_TABS) or ('members' if request.GET.get('uq') else default)


def _filter_context(request, tab):
    """Panneau de filtres de l'onglet : gabarit, valeurs proposées et état (les filtres appartiennent à l'onglet affiché)."""
    if tab == 'beers':
        return {
            'filter_template': 'partials/beer_filters_panel.html', 'styles': catalog_styles(),
            'filtered': any(request.GET.get(param) for param in FILTER_PARAMS),
        }
    if tab in PLACE_TABS:
        kind = PLACE_TABS[tab]
        return {
            'filter_template': 'partials/place_filters.html', 'cities': place_filters.cities(kind.model),
            'styles': catalog_styles() if kind is BREWERY else [], 'is_brewery_tab': kind is BREWERY,
            'filtered': place_filters.is_filtered(request.GET),
        }
    return {}


def _preview(request, getter, kind=None):
    """Premiers résultats d'une rubrique pour l'onglet « Tout »."""
    items = list(getter(request)[:PREVIEW])
    return with_targets(items, kind) if kind else items


def build_results(request, default_tab='beers'):
    """Contexte du bloc de résultats : onglets, et le contenu de l'onglet actif (une seule requête pour l'onglet affiché).

    L'onglet « Tout » regroupe les premiers résultats de chaque rubrique ; sans recherche il n'affiche rien (c'est l'accueil).
    """
    tab, query = active_tab(request, default_tab), search_query(request)
    context = {'tabs': TABS, 'active_tab': tab, 'query': query, 'has_query': bool(search.terms(query))}
    sections = {
        'beers': ('beers', get_filtered_beers),
        'breweries': ('breweries', get_filtered_breweries),
        'bars': ('bars', get_filtered_bars),
        'members': ('users', get_filtered_users),
    }
    if tab == 'all':
        if context['has_query']:
            beers = _preview(request, get_filtered_beers)
            context['all_sections'] = [
                ('beers', "Bières", 'beers', beers),
                ('bars', "Bars", 'places', _preview(request, get_filtered_bars, BAR)),
                ('breweries', "Brasseries", 'places', _preview(request, get_filtered_breweries, BREWERY)),
                ('members', "Membres", 'users', _preview(request, get_filtered_users)),
            ]
            if beers:
                context.update(beer_list_context(request.user, beers))
        return context
    if tab == 'nearby':
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
        context.update(beer_list_context(request.user, context['beers']))
    context.update(_filter_context(request, tab))
    return context


def all_beers_view(request):
    """Page de recherche : barre unique, onglets et résultats."""
    return render(request, 'all_beers.html', build_results(request))


@require_GET
@cache_control(private=True, max_age=300)
@gzip_page  # JSON public sans secret : la compression ne présente pas le risque BREACH des pages
def places_directory(request):
    """Bars et brasseries localisés (données publiques des fiches) : la page « Près de moi » les classe selon la position de l'appareil."""
    return JsonResponse({'places': place_directory.directory()})


@require_GET
def search_api(request):
    """Bloc de résultats seul (saisie en direct, changement d'onglet ou de filtre)."""
    return JsonResponse({'html': render_to_string('partials/search_results.html', build_results(request), request=request)})
