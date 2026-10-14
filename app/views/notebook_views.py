from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib import messages
from urllib.parse import urlencode

from django.db.models import Count, Q, Max

from ..forms import CustomNotebookForm, DrinkForm, error_summary
from ..models import Beer, Drinks, CustomNotebook
from ..services.catalog.selectors import deleted_beers_added_by, get_filtered_notebook_drinks, get_wishlist_beers, rating_bounds
from ..services.catalog import notebooks
from ..services.catalog.styles import styles_in
from ..services.members.profile_stats import get_user_statistics
from .utils import chosen_tab, picker_context

NOTEBOOK_TABS = ('tastings', 'to-taste', 'additions')
NOTEBOOK_TAB_ALIASES = {'carnet': 'tastings', 'collections': 'tastings', 'degustations': 'tastings', 'gouter': 'to-taste', 'ajouts': 'additions'}
CARNET_PAGE = 10
WISHLIST_SORT_OPTIONS = (('date_desc', "Récentes"), ('name_asc', "A à Z"), ('degree_desc', "Plus fortes"), ('ibu_desc', "Plus amères"))

# Tris de la liste d'un carnet, rangés en deux groupes dans la feuille « Filtrer »
SORT_GROUPS = (
    ("Votre avis", (('date_desc', "Dégustation récente"), ('date_asc', "Dégustation ancienne"),
                    ('note_desc', "Meilleure note"), ('note_asc', "Note la plus basse"))),
    ("La bière", (('name_asc', "Nom A à Z"), ('name_desc', "Nom Z à A"), ('style_asc', "Style"),
                  ('degree_desc', "Plus forte"), ('degree_asc', "Plus légère"),
                  ('ibu_desc', "Plus amère"), ('ibu_asc', "Moins amère"))),
)
SORT_LABELS = {value: label for _, options in SORT_GROUPS for value, label in options}
DEGREE_OPTIONS = (('light', "Légères (moins de 5 %)"), ('regular', "Normales (5 à 8 %)"), ('strong', "Fortes (plus de 8 %)"))
IBU_OPTIONS = (('low', "Douces (moins de 20)"), ('medium', "Moyennes (20 à 50)"), ('high', "Amères (plus de 50)"))
MAX_FILTER_TEXT = 100


def filter_summary(params):
    """Filtres actifs : [(paramètre, libellé)]. Sert à compter les filtres affichés sur le bouton « Filtrer » ; le tri est à part."""
    chips = []
    query = (params.get('q') or '').strip()[:MAX_FILTER_TEXT]
    if query:
        chips.append(('q', f"« {query} »"))
    for name, options in (('degree', DEGREE_OPTIONS), ('ibu', IBU_OPTIONS)):
        label = dict(options).get(params.get(name))
        if label:
            chips.append((name, label))
    style = (params.get('style') or '').strip()[:MAX_FILTER_TEXT]
    if style:
        chips.append(('style', style))
    low, high = rating_bounds(params)
    if (low, high) != (0, 10):
        chips.append(('rating', f"Note {low}" if low == high else f"Note {low} à {high}"))
    return chips


def sort_of(params):
    """Tri valide demandé (le tri par défaut sinon : on ne fait jamais confiance au paramètre)."""
    value = params.get('sort')
    return value if value in SORT_LABELS else 'date_desc'


def drinks_list_context(request, drinks):
    """Contexte commun à la page d'un carnet et à son fragment htmx (liste, pastilles, compteur)."""
    params = request.GET
    chips = filter_summary(params)
    sort = sort_of(params)
    page = {key: value for key, value in params.lists() if key != 'offset'}
    querystring = urlencode([(key, value) for key, values in page.items() for value in values])
    return {
        'my_drinks': drinks, 'page_full': len(drinks) == CARNET_PAGE, 'querystring': querystring,
        'sort': sort, 'filter_chips': chips,
        'filter_count': sum(1 for param, _ in chips if param != 'q'),
    }


def notebook_view(request):
    """Page racine du Carnet : statistiques, puis l'onglet choisi (collections, à goûter ou ajouts)."""
    user = request.user

    # Onglets : tastings (par défaut : les collections), to-taste (à goûter), additions (ajouts)
    active_tab = chosen_tab(request.GET.get('tab'), NOTEBOOK_TABS, NOTEBOOK_TAB_ALIASES, default='tastings')

    user_drinks_all = Drinks.objects.filter(drinker=user).select_related('beer', 'beer__brewery').order_by('-date')
    context = {
        **get_user_statistics(user_drinks_all),
        'wishlist_count': user.wishlist_beers.count(),
        'has_drinks': user_drinks_all.exists(),
        'active_tab': active_tab,
        'sort': 'date_desc', 'query': '', 'page_full': False,
    }

    if active_tab == 'tastings':
        picker = picker_context(user, 'drinks')  # fenêtre « Nouveau carnet »
        context.update({
            'custom_notebooks': CustomNotebook.objects.filter(user=user).annotate(drink_count=Count('drinks')),
            'picker': picker,
            'drink_total': picker['total'],
        })
    elif active_tab == 'to-taste':
        wishlist = list(get_wishlist_beers(request)[:CARNET_PAGE])
        context.update({
            'wishlist_beers': wishlist, 'page_full': len(wishlist) == CARNET_PAGE, 'rating_form': DrinkForm(),
            'sort_options': WISHLIST_SORT_OPTIONS,
        })
    else:  # ajouts : requêtes réservées à cet onglet
        context.update({
            'my_added_beers': Beer.objects.filter(added_by=user, is_deleted=False).annotate(
                user_note=Max('drinks__note', filter=Q(drinks__drinker=user))).order_by('-id')[:10],
            'my_deleted_beers': list(deleted_beers_added_by(user)[:CARNET_PAGE]),
            'feedback_on_my_beers': Drinks.objects.filter(beer__added_by=user).exclude(drinker=user)
                .select_related('drinker', 'beer').order_by('-date')[:10],
        })
    return render(request, 'notebook.html', context)


def notebook_wishlist_fragment(request):
    """Liste « À goûter » (recherche et tri en direct : fragment HTML échangé par htmx)."""
    sort = request.GET.get('sort') if request.GET.get('sort') in dict(WISHLIST_SORT_OPTIONS) else 'date_desc'
    request.GET = request.GET.copy()
    request.GET['sort'] = sort
    beers = list(get_wishlist_beers(request)[:CARNET_PAGE])
    return render(request, 'partials/wishlist_list.html', {
        'wishlist_beers': beers, 'page_full': len(beers) == CARNET_PAGE, 'query': (request.GET.get('q') or '').strip(),
        'sort': sort, 'rating_form': DrinkForm(),
    })


def notebook_drinks_fragment(request):
    """Liste filtrée des dégustations d'un carnet (échangée par htmx à chaque saisie ou changement de filtre)."""
    drinks = list(get_filtered_notebook_drinks(request)[:CARNET_PAGE])
    return render(request, 'partials/notebook_drinks_fragment.html', drinks_list_context(request, drinks))


def notebook_detail_view(request, notebook_slug=None):
    """Page d'un carnet (ou de toutes les bières) : recherche, filtres et tri en direct, puis la liste."""
    user = request.user
    notebook = None
    notebook_drink_slugs = []

    if notebook_slug:
        notebook = get_object_or_404(CustomNotebook, slug=notebook_slug, user=user)
        # Le filtre par carnet passe par le même paramètre que le fragment htmx
        request.GET = request.GET.copy()
        request.GET['notebook_slug'] = notebook.slug
        notebook_drink_slugs = list(notebook.drinks.values_list('slug', flat=True))

    my_drinks = list(get_filtered_notebook_drinks(request)[:CARNET_PAGE])
    scope = notebook.drinks.all() if notebook else Drinks.objects.filter(drinker=user)

    rating_min, rating_max = rating_bounds(request.GET)
    context = {
        'notebook': notebook,
        'styles': styles_in(scope),
        'picker': picker_context(user, 'drinks'),  # fenêtre « Modifier le carnet »
        'notebook_drink_slugs': ','.join(notebook_drink_slugs),
        'sort_groups': SORT_GROUPS,
        'degree_options': DEGREE_OPTIONS,
        'ibu_options': IBU_OPTIONS,
        'rating_min': rating_min,
        'rating_max': rating_max,
        'selected_degree': request.GET.get('degree', ''),
        'selected_ibu': request.GET.get('ibu', ''),
        'selected_style': request.GET.get('style', ''),
        'query': (request.GET.get('q') or '').strip()[:MAX_FILTER_TEXT],
        **drinks_list_context(request, my_drinks),
    }
    return render(request, 'notebook_detail.html', context)

@require_POST
def create_custom_notebook(request):
    """Crée un nouveau carnet personnalisé."""
    form = CustomNotebookForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Le carnet n'a pas pu être créé : " + " ; ".join(error_summary(form)))
        return redirect('notebook')
    try:
        notebooks.create(request.user, form, request.POST.getlist('drinks'))
    except notebooks.NotebookLimitReached:
        messages.error(request, f"Vous avez atteint la limite de {notebooks.MAX_NOTEBOOKS} carnets.")
    else:
        messages.success(request, "Carnet créé avec succès !")
    return redirect('notebook')


@require_POST
def delete_custom_notebook(request, notebook_slug):
    """Supprime un carnet personnalisé."""
    notebook = get_object_or_404(CustomNotebook, slug=notebook_slug, user=request.user)
    notebook.delete()
    messages.success(request, "Le carnet a été supprimé.")
    return redirect('notebook')

@require_POST
def edit_custom_notebook(request, notebook_slug):
    """Modifie le titre, la description et les bières d'un carnet personnalisé."""
    notebook = get_object_or_404(CustomNotebook, slug=notebook_slug, user=request.user)
    
    form = CustomNotebookForm(request.POST, instance=notebook)
    if not form.is_valid():
        messages.error(request, "Le carnet n'a pas pu être modifié : " + " ; ".join(error_summary(form)))
        return redirect('notebook_detail', notebook_slug=notebook.slug)

    notebooks.update(notebook, form, request.POST.getlist('drinks'))
    messages.success(request, "Le carnet a été modifié avec succès.")
        
    return redirect('notebook_detail', notebook_slug=notebook.slug)
