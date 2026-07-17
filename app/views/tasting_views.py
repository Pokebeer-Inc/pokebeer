from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from ..forms import DrinkForm
from ..models import Beer, Drinks, BeerSpot, Notification
from .utils import check_and_notify_achievements

@login_required(login_url='login')
def rate_beer_view(request, beer_id):
    """Traite la notation depuis n'importe quelle page"""
    beer = get_object_or_404(Beer, id=beer_id)
    
    previous_url = request.META.get('HTTP_REFERER', 'index')
    
    if Drinks.objects.filter(drinker_id=request.user, beer_id=beer).exists():
        messages.warning(request, f"Vous avez déjà noté la bière {beer.name}.")
        return redirect(previous_url)
    
    if request.method == 'POST':
        form = DrinkForm(request.POST)
        if form.is_valid():
            drink = form.save(commit=False)
            drink.drinker_id = request.user
            drink.beer_id = beer
            drink.save()
            
            # Trouve tous les autres utilisateurs qui ont noté cette bière
            other_drinkers = Drinks.objects.filter(beer_id=beer).exclude(drinker_id=request.user).values_list('drinker_id', flat=True).distinct()
            for d_id in other_drinkers:
                Notification.objects.create(recipient_id=d_id, sender=request.user, notif_type='beer_shared', beer=beer)
            messages.success(request, f"Votre avis sur {beer.name} a été enregistré !")
        else:
            messages.error(request, "Erreur dans le formulaire de notation.")
            
    check_and_notify_achievements(request.user)
    return redirect(previous_url)

@login_required(login_url='login')
def modify_rate_beer_view(request, drink_id):
    """Permet de modifier une note depuis la page de détail d'une bière"""
    drink = get_object_or_404(Drinks, id=drink_id, drinker_id=request.user)
    beer = drink.beer_id
    
    if request.method == 'POST':
        form = DrinkForm(request.POST, instance=drink)
        if form.is_valid():
            form.save()
            messages.success(request, f"Votre avis sur {beer.name} a été mis à jour !")
        else:
            messages.error(request, "Erreur dans le formulaire de modification.")
            
    return redirect('beer_detail', beer_slug=beer.slug)

@login_required(login_url='login')
def delete_drink_view(request, drink_id):
    """Permet de supprimer sa propre note."""
    drink = get_object_or_404(Drinks, id=drink_id, drinker_id=request.user)
    if request.method == 'POST':
        drink.delete()
        messages.success(request, "Votre dégustation a bien été supprimée.")
    return redirect(request.META.get('HTTP_REFERER', 'account'))

@login_required(login_url='login')
def delete_spot_view(request, spot_id):
    """Permet au propriétaire de supprimer son spot sur la carte."""
    spot = get_object_or_404(BeerSpot, id=spot_id, user=request.user)
    if request.method == 'POST':
        spot.delete()
        messages.success(request, "Lieu supprimé de la carte.")
    return redirect('map')
