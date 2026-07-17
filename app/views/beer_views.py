from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.http import JsonResponse
import json

from ..forms import BeerForm, DrinkForm
from ..models import Beer, Drinks, Brewery, Notification, UserFollow
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
            
            # Trouve tous mes abonnés
            followers = UserFollow.objects.filter(followed=request.user).values_list('follower_id', flat=True)
            for f_id in followers:
                Notification.objects.create(recipient_id=f_id, sender=request.user, notif_type='beer_added', beer=new_beer)
            
            from .utils import check_and_notify_achievements
            check_and_notify_achievements(request.user)
            
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
            
            drinkers = Drinks.objects.filter(beer_id=beer).exclude(drinker_id=request.user).values_list('drinker_id', flat=True).distinct()
            
            for d_id in drinkers:
                Notification.objects.create(recipient_id=d_id, sender=request.user, notif_type='beer_updated', beer=beer)
                
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
        
        # Supprimer les notifications liées à cette bière
        Notification.objects.filter(beer=beer).delete()
        
        messages.success(request, "Bière retirée du catalogue. Vos notes personnelles sont conservées.")
        return redirect('index')
    return redirect('beer_detail', beer_slug=beer.slug)

@require_POST
@login_required(login_url='login')
def update_top_beer(request, slot):
    """Met à jour l'un des 3 slots du Top 3 de l'utilisateur."""
    if slot not in [1, 2, 3]:
        messages.error(request, "Emplacement invalide.")
        return redirect('account')

    beer_id = request.POST.get('beer_id')
    user = request.user

    if beer_id:
        beer = get_object_or_404(Beer, id=beer_id)
        
        if (slot != 1 and user.top_beer_1_id == beer.id) or \
           (slot != 2 and user.top_beer_2_id == beer.id) or \
           (slot != 3 and user.top_beer_3_id == beer.id):
            messages.error(request, f"{beer.name} est déjà dans votre Top 3 !")
            return redirect('account')

        if slot == 1: user.top_beer_1 = beer
        elif slot == 2: user.top_beer_2 = beer
        elif slot == 3: user.top_beer_3 = beer
        messages.success(request, f"Bière ajoutée à votre Top {slot} !")
    else:
        # Si aucun ID n'est fourni, on vide l'emplacement
        if slot == 1: user.top_beer_1 = None
        elif slot == 2: user.top_beer_2 = None
        elif slot == 3: user.top_beer_3 = None
        messages.info(request, f"Emplacement Top {slot} vidé.")

    user.save()
    return redirect('account')

@require_POST
@login_required
def swap_top_beers(request):
    """API pour intervertir (drag & drop) deux bières dans le Top 3."""
    try:
        data = json.loads(request.body)
        slot_from = int(data.get('from_slot'))
        slot_to = int(data.get('to_slot'))
        
        if slot_from not in [1, 2, 3] or slot_to not in [1, 2, 3]:
            return JsonResponse({'success': False, 'error': 'Emplacements invalides'}, status=400)

        user = request.user
        
        # Stockage temporaire des bières actuelles pour l'échange
        top_beers = {
            1: user.top_beer_1,
            2: user.top_beer_2,
            3: user.top_beer_3
        }
        
        # Application de l'échange
        if slot_from == 1: user.top_beer_1 = top_beers[slot_to]
        elif slot_from == 2: user.top_beer_2 = top_beers[slot_to]
        elif slot_from == 3: user.top_beer_3 = top_beers[slot_to]
        
        if slot_to == 1: user.top_beer_1 = top_beers[slot_from]
        elif slot_to == 2: user.top_beer_2 = top_beers[slot_from]
        elif slot_to == 3: user.top_beer_3 = top_beers[slot_from]
        
        user.save()
        return JsonResponse({'success': True})
        
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': 'Requête invalide'}, status=400)

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