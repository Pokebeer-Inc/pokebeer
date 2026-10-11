"""« Charger plus » : une seule route (`load_more_generic`), un chargeur déclaré par type de liste.

Ajouter une liste paginée = écrire une fonction décorée par `@loader('nom')` : la vue, la pagination et le rendu ne changent pas.
Un chargeur reçoit la requête, le point de départ et la taille de la page ; il renvoie une `Page` (éléments, gabarit, contexte)
ou lève `LoadMoreError` pour refuser (profil inaccessible, paramètre manquant…).
"""
from dataclasses import dataclass, field

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string

from ..forms import DrinkForm
from ..models import Beer, BeerUser, Drinks, UserBlock
from ..services.members.follows import followers_of, following_of
from ..services.establishments.places import BAR, BREWERY, with_targets
from ..services.catalog.selectors import (
    get_filtered_bars,
    get_filtered_beers,
    get_filtered_breweries,
    get_filtered_notebook_drinks,
    get_filtered_users,
    get_wishlist_beers,
)
from .utils import parse_offset

__all__ = ['load_more_generic']

PAGE_SIZE = 10


class LoadMoreError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.message, self.status = message, status


@dataclass
class Page:
    items: object  # ce qui a été trouvé : vide = plus rien à charger
    template: str
    context: dict = field(default_factory=dict)


LOADERS = {}


def loader(name):
    """Déclare le chargeur d'un type de liste."""
    def register(function):
        LOADERS[name] = function
        return function
    return register


def _blocked_between(user, other):
    return UserBlock.objects.filter(Q(blocker=user, blocked=other) | Q(blocker=other, blocked=user)).exists()


def _profile_from_request(request):
    """Membre dont on charge le profil public (paramètre `username`) : il doit exister, être actif et ne pas être en blocage avec le visiteur."""
    username = request.GET.get('username')
    if not username:
        raise LoadMoreError('Nom utilisateur manquant', 400)
    profile_user = get_object_or_404(BeerUser, username=username, is_active=True)
    if _blocked_between(request.user, profile_user):
        raise LoadMoreError('Profil inaccessible', 403)
    return profile_user


@loader('search_beers')
def search_beers(request, offset, limit):
    beers = get_filtered_beers(request)[offset:offset + limit]
    context = {}
    if beers:
        displayed_ids = [beer.id for beer in beers]
        context = {
            'beers': beers,
            'rating_form': DrinkForm(),
            'rated_beer_ids': list(Drinks.objects.filter(drinker=request.user, beer__in=displayed_ids).values_list('beer', flat=True)),
            'wishlist_beer_ids': list(request.user.wishlist_beers.filter(id__in=displayed_ids).values_list('id', flat=True)),
        }
    return Page(beers, 'partials/search_beers.html', context)


@loader('search_users')
def search_users(request, offset, limit):
    users = get_filtered_users(request)[offset:offset + limit]
    return Page(users, 'partials/search_users.html', {'users': users})


@loader('search_breweries')
def search_breweries(request, offset, limit):
    places = with_targets(get_filtered_breweries(request)[offset:offset + limit], BREWERY)
    return Page(places, 'partials/search_places.html', {'places': places, 'place_kind': 'brewery'})


@loader('search_bars')
def search_bars(request, offset, limit):
    places = with_targets(get_filtered_bars(request)[offset:offset + limit], BAR)
    return Page(places, 'partials/search_places.html', {'places': places, 'place_kind': 'bar'})


@loader('wishlist_tiles')
def wishlist_tiles(request, offset, limit):
    beers = list(get_wishlist_beers(request)[offset:offset + limit])
    return Page(beers, 'partials/wishlist_tiles.html', {'wishlist_beers': beers, 'rating_form': DrinkForm()})


@loader('notebook_drinks')
def notebook_drinks(request, offset, limit):
    drinks = get_filtered_notebook_drinks(request)[offset:offset + limit]
    return Page(drinks, 'partials/notebook_drinks.html', {'my_drinks': drinks})


@loader('added_beers')
def added_beers(request, offset, limit):
    beers = Beer.objects.filter(added_by=request.user, is_deleted=False).annotate(
        user_note=Max('drinks__note', filter=Q(drinks__drinker=request.user))
    ).order_by('-id')[offset:offset + limit]
    return Page(beers, 'partials/notebook_added_beers.html', {'my_added_beers': beers})


@loader('notebook_feedback')
def notebook_feedback(request, offset, limit):
    drinks = (Drinks.objects.filter(beer__added_by=request.user).exclude(drinker=request.user)
              .select_related('drinker', 'beer').order_by('-date')[offset:offset + limit])
    return Page(drinks, 'partials/notebook_feedback.html', {'feedback_on_my_beers': drinks})


def _follow_loader(name, listing):
    @loader(name)
    def load(request, offset, limit):
        user = request.user
        username = request.GET.get('username')
        if username and username != user.username:
            target = _profile_from_request(request)
            variant_owner = 'public_'
        else:
            target, variant_owner = user, 'own_'
        entries = list(listing(target)[offset:offset + limit])
        return Page(entries, 'partials/follow_items.html', {'entries': entries, 'variant': variant_owner + name})
    return load


_follow_loader('followers', followers_of)
_follow_loader('following', following_of)


@loader('public_added_beers')
def public_added_beers(request, offset, limit):
    profile_user = _profile_from_request(request)
    beers = Beer.objects.filter(added_by=profile_user, is_deleted=False).annotate(
        user_note=Max('drinks__note', filter=Q(drinks__drinker=profile_user)),
        count_rating=Count('drinks')
    ).order_by('-id')[offset:offset + limit]
    return Page(beers, 'partials/public_added_beers.html', {'user_added_beers': beers})


@loader('public_drinks')
def public_drinks(request, offset, limit):
    profile_user = _profile_from_request(request)
    drinks = Drinks.objects.filter(drinker=profile_user).select_related('beer', 'beer__brewery').order_by('-date')[offset:offset + limit]
    return Page(drinks, 'partials/public_drinks.html', {'user_drinks': drinks})


@login_required(login_url='login')
def load_more_generic(request, item_type):
    """API générique unique pour tous les chargements dynamiques (« Charger plus »)."""
    offset = parse_offset(request)
    if offset is None:
        return JsonResponse({'error': 'Offset invalide'}, status=400)
    load = LOADERS.get(item_type)
    if load is None:
        return JsonResponse({'error': 'Type de liste invalide'}, status=400)
    try:
        page = load(request, offset, PAGE_SIZE)
    except LoadMoreError as error:
        return JsonResponse({'error': error.message}, status=error.status)

    if not page.items:
        return JsonResponse({'html': '', 'has_more': False})
    html = render_to_string(page.template, page.context, request=request)
    return JsonResponse({'html': html, 'has_more': len(page.items) == PAGE_SIZE})
