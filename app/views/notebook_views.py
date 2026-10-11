from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from urllib.parse import urlencode

from django.db.models import Count, Q, Max

from ..forms import CustomNotebookForm, DrinkForm, error_summary
from ..models import Beer, Drinks, CustomNotebook
from .services.selectors import get_filtered_notebook_drinks, get_wishlist_beers
from .services.stats import get_user_statistics

NOTEBOOK_TABS = ('tastings', 'to-taste', 'additions')
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


def rating_bounds(params):
    """Fourchette de notes demandée, bornée à 0-10 (valeurs invalides ignorées)."""
    def number(name, default):
        value = params.get(name, '')
        return min(10, max(0, int(value))) if value.isdigit() else default
    low, high = number('rating_min', 0), number('rating_max', 10)
    return (low, high) if low <= high else (high, low)


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


@login_required(login_url='login')
def notebook_view(request):
    """Page racine du Carnet : statistiques, puis l'onglet choisi (collections, à goûter ou ajouts)."""
    user = request.user

    # Onglets : tastings (par défaut : les collections), to-taste (à goûter), additions (ajouts) ; les anciens noms français restent acceptés
    active_tab = request.GET.get('tab', 'tastings')
    active_tab = {'carnet': 'tastings', 'collections': 'tastings', 'degustations': 'tastings', 'gouter': 'to-taste', 'ajouts': 'additions'}.get(active_tab, active_tab)
    if active_tab not in NOTEBOOK_TABS:
        active_tab = 'tastings'

    user_drinks_all = Drinks.objects.filter(drinker_id=user).select_related('beer_id', 'beer_id__brewery_id').order_by('-date')
    context = {
        **get_user_statistics(user_drinks_all),
        'wishlist_count': user.wishlist_beers.count(),
        'has_drinks': user_drinks_all.exists(),
        'active_tab': active_tab,
        'sort': 'date_desc', 'query': '', 'page_full': False,
    }

    if active_tab == 'tastings':
        context.update({
            'custom_notebooks': CustomNotebook.objects.filter(user=user).annotate(drink_count=Count('drinks')),
            'user_drinks_all': user_drinks_all,  # cases à cocher de la fenêtre « Nouveau carnet »
            'drink_total': user_drinks_all.count(),
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
                user_note=Max('drinks__note', filter=Q(drinks__drinker_id=user))).order_by('-id')[:10],
            'my_deleted_beers': Beer.objects.filter(added_by=user, is_deleted=True).annotate(
                user_note=Max('drinks__note', filter=Q(drinks__drinker_id=user))).order_by('-id'),
            'feedback_on_my_beers': Drinks.objects.filter(beer_id__added_by=user).exclude(drinker_id=user)
                .select_related('drinker_id', 'beer_id').order_by('-date')[:10],
        })
    return render(request, 'notebook.html', context)


@login_required(login_url='login')
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


@login_required(login_url='login')
def notebook_drinks_fragment(request):
    """Liste filtrée des dégustations d'un carnet (échangée par htmx à chaque saisie ou changement de filtre)."""
    drinks = list(get_filtered_notebook_drinks(request)[:CARNET_PAGE])
    return render(request, 'partials/notebook_drinks_fragment.html', drinks_list_context(request, drinks))


def _styles_of(drinks):
    """Styles présents dans ces dégustations (un champ peut en contenir plusieurs, séparés par des virgules)."""
    raw = drinks.exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values_list('beer_id__style', flat=True).distinct()
    return sorted({style.strip() for value in raw for style in value.split(',') if style.strip()})


@login_required(login_url='login')
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
    user_drinks_all = Drinks.objects.filter(drinker_id=user).select_related('beer_id', 'beer_id__brewery_id').order_by('-date')  # fenêtre « Modifier le carnet »
    scope = notebook.drinks.all() if notebook else user_drinks_all

    context = {
        'notebook': notebook,
        'styles': _styles_of(scope),
        'user_drinks_all': user_drinks_all,
        'notebook_drink_slugs': notebook_drink_slugs,
        'sort_groups': SORT_GROUPS,
        'degree_options': DEGREE_OPTIONS,
        'ibu_options': IBU_OPTIONS,
        'rating_min': rating_bounds(request.GET)[0],
        'rating_max': rating_bounds(request.GET)[1],
        'selected_degree': request.GET.get('degree', ''),
        'selected_ibu': request.GET.get('ibu', ''),
        'selected_style': request.GET.get('style', ''),
        'query': (request.GET.get('q') or '').strip()[:MAX_FILTER_TEXT],
        **drinks_list_context(request, my_drinks),
    }
    return render(request, 'notebook_detail.html', context)

@require_POST
@login_required(login_url='login')
def create_custom_notebook(request):
    """Crée un nouveau carnet personnalisé."""
    if request.user.custom_notebooks.count() >= 50:
        messages.error(request, "Vous avez atteint la limite de 50 carnets.")
        return redirect('notebook')
        
    form = CustomNotebookForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Le carnet n'a pas pu être créé : " + " ; ".join(error_summary(form)))
        return redirect('notebook')

    notebook = form.save(commit=False)
    notebook.user = request.user
    notebook.save()
    drink_slugs = request.POST.getlist('drinks')
    if drink_slugs:
        notebook.drinks.set(Drinks.objects.filter(slug__in=drink_slugs, drinker_id=request.user))
    messages.success(request, "Carnet créé avec succès !")
        
    return redirect('notebook')

@require_POST
@login_required(login_url='login')
def delete_custom_notebook(request, notebook_slug):
    """Supprime un carnet personnalisé."""
    notebook = get_object_or_404(CustomNotebook, slug=notebook_slug, user=request.user)
    notebook.delete()
    messages.success(request, "Le carnet a été supprimé.")
    return redirect('notebook')

@require_POST
@login_required(login_url='login')
def edit_custom_notebook(request, notebook_slug):
    """Modifie le titre, la description et les bières d'un carnet personnalisé."""
    notebook = get_object_or_404(CustomNotebook, slug=notebook_slug, user=request.user)
    
    form = CustomNotebookForm(request.POST, instance=notebook)
    if not form.is_valid():
        messages.error(request, "Le carnet n'a pas pu être modifié : " + " ; ".join(error_summary(form)))
        return redirect('notebook_detail', notebook_slug=notebook.slug)

    form.save()
    notebook.drinks.set(Drinks.objects.filter(slug__in=request.POST.getlist('drinks'), drinker_id=request.user))
    messages.success(request, "Le carnet a été modifié avec succès.")
        
    return redirect('notebook_detail', notebook_slug=notebook.slug)
