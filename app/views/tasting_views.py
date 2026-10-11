from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.urls import reverse

from ..forms import DrinkForm, error_summary
from ..models import Beer, Drinks
from ..services.members.achievements import check_and_notify_achievements
from .utils import posted_notebooks, previous_page
from ..services.catalog.drinks import delete_drink
from ..services.messaging.notifications import notify

RATE_RETURN_KEY = 'rate_return_url'  # page d'où le membre a noté (déjà contrôlée par previous_page : jamais une adresse étrangère)


@login_required(login_url='login')
def rate_beer_view(request, beer_slug):
    """Traite la notation depuis n'importe quelle page"""
    beer = get_object_or_404(Beer, slug=beer_slug)
    
    previous_url = previous_page(request)
    
    if Drinks.objects.filter(drinker=request.user, beer=beer).exists():
        messages.warning(request, f"Vous avez déjà noté la bière {beer.name}.")
        return redirect(previous_url)
    
    if request.method == 'POST':
        form = DrinkForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            drink = form.save(commit=False)
            drink.drinker = request.user
            drink.beer = beer
            try:
                with transaction.atomic():
                    drink.save()
            except IntegrityError:
                # Deux envois simultanés (double clic) : la contrainte d'unicité en base a le dernier mot, la première note est conservée
                messages.warning(request, f"Vous avez déjà noté la bière {beer.name}.")
                return redirect(previous_url)

            drink.notebooks.add(*posted_notebooks(request))
            
            # Si la biere est notée, alors il faut l'enlever de la wishlist
            if beer in request.user.wishlist_beers.all():
                request.user.wishlist_beers.remove(beer)
            
            # Trouve tous les autres utilisateurs qui ont noté cette bière
            other_drinkers = Drinks.objects.filter(beer=beer).exclude(drinker=request.user).values_list('drinker', flat=True).distinct()
            
            notify('beer_shared', other_drinkers, sender=request.user, beer=beer)
            
            check_and_notify_achievements(request.user)
            # Page de félicitations, comme après l'ajout d'une bière ; la page d'origine est gardée côté serveur pour le bouton « Retour »
            request.session[RATE_RETURN_KEY] = previous_url
            return redirect('rate_beer_done', beer_slug=beer.slug)
        messages.error(request, "Erreur dans le formulaire de notation : " + " ; ".join(error_summary(form)))

    return redirect(previous_url)


@login_required(login_url='login')
def rate_beer_done_view(request, beer_slug):
    """Page de félicitations après une notation (réservée à la personne qui vient de noter cette bière)."""
    drink = get_object_or_404(Drinks.objects.select_related('beer', 'beer__brewery'), beer__slug=beer_slug, drinker=request.user, beer__is_deleted=False)
    return render(request, 'rate_beer_done.html', {
        'drink': drink,
        'beer': drink.beer,
        'drinks_count': Drinks.objects.filter(drinker=request.user).count(),
        'return_url': request.session.get(RATE_RETURN_KEY) or reverse('beer_detail', args=[beer_slug]),
    })

@login_required(login_url='login')
def modify_rate_beer_view(request, drink_slug):
    """Permet de modifier une note depuis la page de détail d'une bière"""
    drink = get_object_or_404(Drinks, slug=drink_slug, drinker=request.user)
    beer = drink.beer
    
    if request.method == 'POST':
        form = DrinkForm(request.POST, request.FILES, instance=drink, user=request.user)
        if form.is_valid():
            form.save()
            
            # Mise à jour des carnets
            # Retire la dégustation de tous les carnets de l'utilisateur
            user_notebooks = request.user.custom_notebooks.all()
            drink.notebooks.remove(*user_notebooks)
            
            # Ré-ajoute aux carnets cochés 
            drink.notebooks.add(*posted_notebooks(request))
            
            check_and_notify_achievements(request.user)
            
            messages.success(request, f"Votre avis sur {beer.name} a été mis à jour !")
        else:
            messages.error(request, "Erreur dans le formulaire de modification : " + " ; ".join(error_summary(form)))
            
    return redirect('beer_detail', beer_slug=beer.slug)

@login_required(login_url='login')
def delete_drink_view(request, drink_slug):
    """Permet de supprimer sa propre note."""
    drink = get_object_or_404(Drinks, slug=drink_slug, drinker=request.user)
    
    if request.method == 'POST':
        delete_drink(drink)
        
        check_and_notify_achievements(request.user)
        
        messages.success(request, "Votre dégustation a bien été supprimée.")

    return redirect(previous_page(request, 'account'))
