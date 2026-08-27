from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q, F

from ..forms import BeerForm, DrinkForm
from ..models import Beer, Drinks, Notification, UserFollow, DrinkReaction
from .utils import get_excluded_users, check_and_notify_achievements
from ..services.realtime_service import broadcast_notifications

@login_required(login_url='login')
def add_beer_view(request):
    """Crée une bière ET ajoute une première note automatiquement."""
    if request.method == 'POST':
        beer_form = BeerForm(request.POST, request.FILES, prefix='beer', user=request.user)
        drink_form = DrinkForm(request.POST, prefix='drink')
        
        if beer_form.is_valid() and drink_form.is_valid():
            new_beer = beer_form.save(user=request.user)
            new_drink = drink_form.save(commit=False)
            new_drink.drinker_id = request.user
            new_drink.beer_id = new_beer
            new_drink.save()
            
            notebook_ids = request.POST.getlist('notebooks')
            if notebook_ids:
                notebooks = request.user.custom_notebooks.filter(id__in=notebook_ids)
                for nb in notebooks:
                    nb.drinks.add(new_drink)
            
            # Trouve tous mes abonnés
            followers = UserFollow.objects.filter(followed=request.user).values_list('follower_id', flat=True)
            # Création en masse
            notifications = [
                Notification(recipient_id=f_id, sender=request.user, notif_type='beer_added', beer=new_beer)
                for f_id in followers
            ]
            created_notifs = Notification.objects.bulk_create(notifications)
            broadcast_notifications(created_notifs)
            
            if new_beer.brewery_id:
                managers = new_beer.brewery_id.managers.exclude(id=request.user.id) # Exclut si le créateur EST le manager
                if managers.exists():
                    manager_notifs = [
                        Notification(recipient=m, sender=request.user, notif_type='beer_added_to_brewery', beer=new_beer)
                        for m in managers
                    ]
                    created_manager_notifs = Notification.objects.bulk_create(manager_notifs)
                    broadcast_notifications(created_manager_notifs)
            
            check_and_notify_achievements(request.user)
            
            messages.success(request, f"Bière ajoutée et notée ! Merci {request.user.username}.")
            return redirect('index')
        else:
            messages.error(request, "Erreur dans le formulaire. Veuillez vérifier les champs.")
    else:
        # On lit le paramètre dans l'URL ?brewery=
        initial_brewery = request.GET.get('brewery', '')
        
        # On l'injecte dans le champ 'brewery_name' du formulaire
        beer_form = BeerForm(prefix='beer', initial={'brewery_name': initial_brewery}, user=request.user)
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
    
    # Calcul du Score (Likes - Dislikes) et Tri
    drinks = Drinks.objects.filter(beer_id=beer).exclude(drinker_id__in=get_excluded_users(request.user)).select_related('drinker_id')
    drinks = drinks.annotate(
        likes=Count('reactions', filter=Q(reactions__is_like=True)),
        dislikes=Count('reactions', filter=Q(reactions__is_like=False))
    ).annotate(
        score=F('likes') - F('dislikes')
    ).order_by('-score', '-date')

    # Identifier les réactions de l'utilisateur connecté pour l'UI
    user_reactions = {}
    if request.user.is_authenticated:
        reactions = DrinkReaction.objects.filter(user=request.user, drink__in=drinks).values_list('drink_id', 'is_like')
        user_reactions = {r[0]: r[1] for r in reactions}
    
    for drink in drinks:
        drink.user_reaction = user_reactions.get(drink.id, None)

    # Format
    user_rating = None
    user_drink = drinks.filter(drinker_id=request.user).first() if request.user.is_authenticated else None
    if user_drink:
        user_rating = {
            'note': user_drink.note,
            'comment': user_drink.comment,
            'date': user_drink.date,
            'id': user_drink.id,
            'likes': getattr(user_drink, 'likes', 0),
            'dislikes': getattr(user_drink, 'dislikes', 0),
            'notebook_ids': list(user_drink.notebooks.values_list('id', flat=True))
        }
        rating_from = DrinkForm()
        rating_from.fields['date'].initial = user_drink.date
        rating_from.fields['note'].initial = user_drink.note
        rating_from.fields['comment'].initial = user_drink.comment
    else:
        rating_from = DrinkForm()

    wishlist_beer_ids = []
    is_brewery_manager = False # NOUVEAU
    
    if request.user.is_authenticated:
        if request.user.wishlist_beers.filter(id=beer.id).exists():
            wishlist_beer_ids.append(beer.id)
            
        # On vérifie si le user est manager de la brasserie liée à cette bière
        if beer.brewery_id:
            is_brewery_manager = beer.brewery_id.managers.filter(id=request.user.id).exists()

    context = {
        'beer': beer,
        'drinks': drinks,
        'is_brewery_manager': is_brewery_manager,
        'user_rating': user_rating,
        'rating_form': rating_from,
        'wishlist_beer_ids': wishlist_beer_ids,
    }
    return render(request, 'beer_page.html', context)

@login_required(login_url='login')
def edit_beer_view(request, beer_slug):
    """Éditer les infos d'une bière qu'on a proposée ou dont on gère la brasserie."""
    
    beer = get_object_or_404(Beer, slug=beer_slug, is_deleted=False)
    
    # Vérification des droits (Créateur OU Manager)
    is_creator = (beer.added_by == request.user)
    is_manager = beer.brewery_id and beer.brewery_id.managers.filter(id=request.user.id).exists()
    
    if not (is_creator or is_manager):
        messages.error(request, "Vous n'avez pas l'autorisation de modifier cette bière.")
        return redirect('beer_detail', beer_slug=beer.slug)

    if request.method == 'POST':
        form = BeerForm(request.POST, request.FILES, instance=beer, user=request.user)
        if form.is_valid():
            form.save()
            
            drinkers = Drinks.objects.filter(beer_id=beer).exclude(drinker_id=request.user).values_list('drinker_id', flat=True).distinct()
            
            notifications = [
                Notification(recipient_id=d_id, sender=request.user, notif_type='beer_updated', beer=beer)
                for d_id in drinkers
            ]
            created_notifs = Notification.objects.bulk_create(notifications)
            broadcast_notifications(created_notifs)
            
            if is_manager and not is_creator and beer.added_by:
                notif_creator = Notification.objects.create(
                    recipient=beer.added_by,
                    sender=request.user,
                    notif_type='beer_updated_by_manager',
                    beer=beer
                )
                broadcast_notifications([notif_creator])
                
            messages.success(request, "Les informations de la bière ont été mises à jour.")
            return redirect('beer_detail', beer_slug=beer.slug)
    else:
        form = BeerForm(instance=beer, user=request.user)
    return render(request, 'edit_beer.html', {'form': form, 'beer': beer})

@login_required(login_url='login')
def delete_beer_view(request, beer_slug):
    """Soft-delete d'une bière du catalogue."""
    
    beer = get_object_or_404(Beer, slug=beer_slug, is_deleted=False)
    
    # Vérification des droits
    is_creator = (beer.added_by == request.user)
    is_manager = beer.brewery_id and beer.brewery_id.managers.filter(id=request.user.id).exists()
    
    if not (is_creator or is_manager):
        messages.error(request, "Vous n'avez pas l'autorisation de retirer cette bière.")
        return redirect('beer_detail', beer_slug=beer.slug)

    if request.method == 'POST':
        beer.is_deleted = True
        beer.save()
        
        # Supprimer les notifications liées à cette bière
        Notification.objects.filter(beer=beer).delete()
        
        if beer.added_by:
            check_and_notify_achievements(beer.added_by)
        
        if is_manager and not is_creator and beer.added_by:
            notif_creator = Notification.objects.create(
                recipient=beer.added_by,
                sender=request.user,
                notif_type='beer_deleted_by_manager',
                text_content=beer.name  # On utilise le texte libre car la bière est désormais cachée
            )
            broadcast_notifications([notif_creator])
        
        messages.success(request, "Bière retirée du catalogue. Vos notes personnelles sont conservées.")
        return redirect('index')
    return redirect('beer_detail', beer_slug=beer.slug)
