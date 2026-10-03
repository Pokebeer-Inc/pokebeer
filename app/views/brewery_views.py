from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required

from ..forms import DrinkForm
from ..models import Beer, Drinks, Brewery
from .place_views import (
    BREWERY, add_manager, edit_place, place_context, remove_manager, search_users_for_manager,
)

@login_required(login_url='login')
def brewery_detail_view(request, brewery_slug):
    """Affiche les détails d'une brasserie et la liste de ses bières."""
    brewery = get_object_or_404(Brewery, slug=brewery_slug)
    beers = Beer.objects.filter(brewery_id=brewery, is_deleted=False).order_by('name')

    # Limiter aux bières de cette brasserie
    rated_beer_ids = []
    wishlist_beer_ids = []
    if request.user.is_authenticated:
        displayed_ids = [b.id for b in beers]
        rated_beer_ids = list(Drinks.objects.filter(drinker_id=request.user, beer_id__in=displayed_ids).values_list('beer_id', flat=True))
        wishlist_beer_ids = list(request.user.wishlist_beers.filter(id__in=displayed_ids).values_list('id', flat=True))

    rating_form = DrinkForm()

    context = {
        'brewery': brewery,
        'beers': beers,
        'rated_beer_ids': rated_beer_ids,
        'wishlist_beer_ids': wishlist_beer_ids,
        'rating_form': rating_form,
        **place_context(brewery, request.user),
    }
    return render(request, 'brewery_page.html', context)

@login_required(login_url='login')
def edit_brewery_view(request, brewery_slug):
    """Permet aux managers de modifier les informations de la brasserie."""
    return edit_place(request, BREWERY, brewery_slug)


@login_required(login_url='login')
def add_brewery_manager(request, brewery_slug):
    """Ajoute un utilisateur comme collaborateur."""
    return add_manager(request, BREWERY, brewery_slug)


@login_required(login_url='login')
def remove_brewery_manager(request, brewery_slug, username):
    """Retire l'accès à un collaborateur (sauf soi-même)."""
    return remove_manager(request, BREWERY, brewery_slug, username)


@login_required(login_url='login')
def api_search_users_for_manager(request, brewery_slug):
    """Recherche AJAX de collaborateurs pour une brasserie."""
    return search_users_for_manager(request, BREWERY, brewery_slug)
