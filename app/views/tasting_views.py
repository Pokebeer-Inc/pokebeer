from django.shortcuts import redirect, render, get_object_or_404
from django.contrib import messages
from django.urls import reverse

from ..forms import DrinkForm, QuickDrinkForm, error_summary
from ..models import Beer, Drinks
from .utils import posted_notebooks, previous_page
from ..services.catalog import drinks

RATE_RETURN_KEY = 'rate_return_url'  # page d'où le membre a noté (déjà contrôlée par previous_page : jamais une adresse étrangère)


def _rate(request, beer_slug, form_class, return_url=None):
    """Enregistre la note d'un membre avec le formulaire donné, puis mène à la page de félicitations. Une erreur ramène à la page d'origine.
    `return_url` : où le bouton « Continuer » de la page de félicitations ramène (par défaut, la page d'où le membre a noté)."""
    beer = get_object_or_404(Beer, slug=beer_slug, is_deleted=False)
    previous_url = previous_page(request)

    if Drinks.objects.filter(drinker=request.user, beer=beer).exists():
        messages.warning(request, f"Vous avez déjà noté la bière {beer.name}.")
        return redirect(previous_url)

    if request.method == 'POST':
        form = form_class(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            try:
                drinks.rate(request.user, beer, form.save(commit=False), posted_notebooks(request))
            except drinks.AlreadyRated:
                messages.warning(request, f"Vous avez déjà noté la bière {beer.name}.")
                return redirect(previous_url)
            # Page de félicitations, comme après l'ajout d'une bière ; la page d'origine est gardée côté serveur pour le bouton « Retour »
            request.session[RATE_RETURN_KEY] = return_url or previous_url
            return redirect('rate_beer_done', beer_slug=beer.slug)
        messages.error(request, "Erreur dans le formulaire de notation : " + " ; ".join(error_summary(form)))

    return redirect(previous_url)


def rate_beer_view(request, beer_slug):
    """Traite la notation depuis n'importe quelle page (bières du catalogue seulement : une bière retirée ne reçoit plus de nouvel avis)."""
    return _rate(request, beer_slug, DrinkForm)


def quick_rate_beer_view(request, beer_slug):
    """Première réaction juste après l'ajout d'une bière : une note ou quelques mots suffisent ; la fiche de la bière permet de préciser ensuite."""
    return _rate(request, beer_slug, QuickDrinkForm, return_url=reverse('beer_detail', args=[beer_slug]))


def rate_beer_done_view(request, beer_slug):
    """Page de félicitations après une notation (réservée à la personne qui vient de noter cette bière)."""
    drink = get_object_or_404(Drinks.objects.select_related('beer', 'beer__brewery'), beer__slug=beer_slug, drinker=request.user, beer__is_deleted=False)
    return render(request, 'rate_beer_done.html', {
        'drink': drink,
        'beer': drink.beer,
        'drinks_count': Drinks.objects.filter(drinker=request.user).count(),
        'return_url': request.session.get(RATE_RETURN_KEY) or reverse('beer_detail', args=[beer_slug]),
    })

def modify_rate_beer_view(request, drink_slug):
    """Permet de modifier une note depuis la page de détail d'une bière"""
    drink = get_object_or_404(Drinks, slug=drink_slug, drinker=request.user)
    beer = drink.beer
    
    if request.method == 'POST':
        form = DrinkForm(request.POST, request.FILES, instance=drink, user=request.user)
        if form.is_valid():
            drinks.update(form, request.user, posted_notebooks(request))
            messages.success(request, f"Votre avis sur {beer.name} a été mis à jour !")
        else:
            messages.error(request, "Erreur dans le formulaire de modification : " + " ; ".join(error_summary(form)))
            
    return redirect('beer_detail', beer_slug=beer.slug)

def delete_drink_view(request, drink_slug):
    """Permet de supprimer sa propre note."""
    drink = get_object_or_404(Drinks, slug=drink_slug, drinker=request.user)
    
    if request.method == 'POST':
        drinks.delete_own(drink)
        
        messages.success(request, "Votre dégustation a bien été supprimée.")

    return redirect(previous_page(request, 'account'))
