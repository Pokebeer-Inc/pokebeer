from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from ..forms import BeerForm, DrinkForm
from ..models import Beer, Drinks, Brewery
from .utils import get_excluded_users

@login_required(login_url='login')
def add_beer_view(request):
    """Crée une bière ET ajoute une première note automatiquement."""
    if request.method == 'POST':
        beer_form = BeerForm(request.POST, prefix='beer')
        drink_form = DrinkForm(request.POST, prefix='drink')
        
        if beer_form.is_valid() and drink_form.is_valid():
            new_beer = beer_form.save(user=request.user)
            new_drink = drink_form.save(commit=False)
            new_drink.drinker_id = request.user
            new_drink.beer_id = new_beer
            new_drink.save()
            
            messages.success(request, f"Bière ajoutée et notée ! Merci {request.user.username}.")
            return redirect('index')
        else:
            messages.error(request, "Erreur dans le formulaire. Veuillez vérifier les champs.")
    else:
        beer_form = BeerForm(prefix='beer')
        drink_form = DrinkForm(prefix='drink')

    context = {
        'beer_form': beer_form, 
        'drink_form': drink_form
    }
    return render(request, 'add_beer.html', context)

@login_required(login_url='login')
def beer_detail_view(request, beer_slug):
    """Affiche les détails d'une bière, ses notes et commentaires."""
    beer = get_object_or_404(Beer, slug=beer_slug)
    drinks = Drinks.objects.filter(beer_id=beer).exclude(drinker_id__in=get_excluded_users(request.user)).select_related('drinker_id').order_by('-date')

    user_rating = None
    user_drink = drinks.filter(drinker_id=request.user).first() if request.user.is_authenticated else None
    if user_drink:
        user_rating = {
            'note': user_drink.note,
            'comment': user_drink.comment,
            'date': user_drink.date,
            'id': user_drink.id
        }
        rating_from = DrinkForm()
        rating_from.fields['date'].initial = user_drink.date
        rating_from.fields['note'].initial = user_drink.note
        rating_from.fields['comment'].initial = user_drink.comment
    else:
        rating_from = DrinkForm()

    context = {
        'beer': beer,
        'drinks': drinks,
        'user_rating': user_rating,
        'rating_form': rating_from
    }

    return render(request, 'beer_page.html', context)

@login_required(login_url='login')
def edit_beer_view(request, beer_slug):
    """Éditer les infos d'une bière qu'on a proposée."""
    beer = get_object_or_404(Beer, slug=beer_slug, added_by=request.user, is_deleted=False)
    if request.method == 'POST':
        form = BeerForm(request.POST, request.FILES, instance=beer)
        if form.is_valid():
            form.save()
            messages.success(request, "Les informations de la bière ont été mises à jour.")
            return redirect('beer_detail', beer_slug=beer.slug)
    else:
        form = BeerForm(instance=beer)
    return render(request, 'edit_beer.html', {'form': form, 'beer': beer})

@login_required(login_url='login')
def delete_beer_view(request, beer_slug):
    """Soft-delete d'une bière du catalogue."""
    beer = get_object_or_404(Beer, slug=beer_slug, added_by=request.user, is_deleted=False)
    if request.method == 'POST':
        beer.is_deleted = True
        beer.save()
        messages.success(request, "Bière retirée du catalogue. Vos notes personnelles sont conservées.")
        return redirect('index')
    return redirect('beer_detail', beer_slug=beer.slug)

@login_required(login_url='login')
def brewery_detail_view(request, brewery_id):
    """Affiche les détails d'une brasserie et la liste de ses bières."""
    brewery = get_object_or_404(Brewery, id=brewery_id)
    beers = Beer.objects.filter(brewery_id=brewery, is_deleted=False).order_by('name')

    rated_beer_ids = []
    if request.user.is_authenticated:
        rated_beer_ids = list(Drinks.objects.filter(drinker_id=request.user).values_list('beer_id', flat=True))

    rating_form = DrinkForm()

    context = {
        'brewery': brewery,
        'beers': beers,
        'rated_beer_ids': rated_beer_ids,
        'rating_form': rating_form,
    }
    return render(request, 'brewery_page.html', context)