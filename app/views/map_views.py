from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_GET
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone

from ..models import BeerSpot, UserFollow
from ..forms import BeerSpotForm, error_summary
from ..services.members.visibility import exclude_hidden_users
from ..services.establishments import place_directory, spots
from ..services.establishments.places import PLACE_KINDS_BY_KEY
from .utils import picker_context

def _save_spot(request):
    """Création ou modification (si `spot_slug` est envoyé) d'un lieu à partir de la fenêtre de la carte."""
    form = BeerSpotForm(request.POST, request.FILES, user=request.user)
    if not form.is_valid():
        messages.error(request, "Le point n'a pas pu être enregistré : " + " ; ".join(error_summary(form)))
        return redirect('map')

    data = form.cleaned_data
    fields = {
        'title': data['title'], 'description': data['description'], 'date': data['date'] or timezone.localdate(),
        'latitude': data['lat'], 'longitude': data['lng'], **form.photo_change(),
    }
    drink_slugs = request.POST.getlist('drinks')
    friend_ids = spots.invitable_friends(request.user, request.POST.getlist('friends'))

    if data['spot_slug']:  # S'il y a un slug, c'est une modification
        spot = get_object_or_404(BeerSpot, slug=data['spot_slug'])
        if spots.can_edit(spot, request.user):
            spots.update_spot(spot, request.user, fields, drink_slugs, friend_ids)
            messages.success(request, "Point modifié avec succès !")
        else:
            messages.error(request, "Action non autorisée.")
    else:
        spots.create_spot(request.user, fields, drink_slugs, friend_ids)
        messages.success(request, "Point ajouté avec succès !")
    return redirect('map')


def map_view(request):
    # Les abonnés de l'utilisateur (les gens qui LE suivent)
    followers = UserFollow.objects.filter(followed=request.user, follower__is_active=True).select_related('follower')
    
    if request.method == 'POST':
        return _save_spot(request)

    # Récupérer : Mes propres lieux + Les lieux où je suis tagué comme ami
    user_spots = exclude_hidden_users(
        BeerSpot.objects.filter(Q(user=request.user) | Q(friends=request.user)), request.user, 'user',
    ).distinct().prefetch_related('drinks', 'drinks__beer', 'friends')
    
    # Afficher les bars et les brasseries
    markers = place_directory.map_markers()
    bars, breweries = markers['bar'], markers['brewery']

    context = {
        'picker': picker_context(request.user, 'drinks'),  # dégustations bues au lieu
        'user_spots': user_spots,
        'followers': followers,
        'bars': bars,
        'breweries': breweries,
    }
    return render(request, 'map.html', context)

def delete_spot_view(request, spot_slug):
    """Permet au propriétaire de supprimer son spot sur la carte."""
    spot = get_object_or_404(BeerSpot, slug=spot_slug, user=request.user)
    if request.method == 'POST':
        spot.delete()
        messages.success(request, "Lieu supprimé de la carte.")
    return redirect('map')


@require_GET
def place_popup_view(request, kind, slug):
    """Contenu de la bulle d'un bar ou d'une brasserie sur la carte, demandé au clic (fragment HTML)."""
    place_kind = PLACE_KINDS_BY_KEY.get(kind)
    if place_kind is None:
        raise Http404
    place = get_object_or_404(place_kind.model.objects.only('slug', 'name', 'description', 'image', 'postal_code', 'city'), slug=slug)
    return render(request, 'partials/map_place_popup.html', {'place': place, 'detail_url': place_kind.detail_path(place)})
