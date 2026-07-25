from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone

from ..models import Drinks, BeerSpot, UserFollow, Notification
from .utils import get_excluded_users, check_and_notify_achievements

@login_required(login_url='login')
def map_view(request):
    # Les abonnés de l'utilisateur (les gens qui LE suivent)
    followers = UserFollow.objects.filter(followed=request.user).select_related('follower')
    
    # Ses dégustations
    user_drinks = Drinks.objects.filter(drinker_id=request.user).select_related('beer_id').order_by('-date')
    
    if request.method == 'POST':
        spot_id = request.POST.get('spot_id') # S'il y a un ID, c'est une modification
        title = request.POST.get('title')
        description = request.POST.get('description')
        date_spot = request.POST.get('date', timezone.now().date())
        lat = request.POST.get('lat')
        lng = request.POST.get('lng')
        drink_ids = request.POST.getlist('drinks')
        friend_ids = request.POST.getlist('friends')
        
        if title and lat and lng:
            if spot_id:
                # --- MODE MODIFICATION ---
                spot = get_object_or_404(BeerSpot, id=spot_id)
                
                # Vérification des droits : Créateur OU Ami associé
                if request.user == spot.user or request.user in spot.friends.all():
                    spot.title = title
                    spot.description = description
                    spot.date = date_spot
                    spot.latitude = float(lat)
                    spot.longitude = float(lng)
                    spot.save()
                    
                    user_current_drinks = spot.drinks.filter(drinker_id=request.user)
                    spot.drinks.remove(*user_current_drinks)
                    if drink_ids:
                        # On identifie les bières déjà ajoutées par les autres sur ce point
                        beers_from_others = spot.drinks.exclude(drinker_id=request.user).values_list('beer_id', flat=True)
                        # On ne garde que les dégustations dont la bière n'est pas déjà présente
                        valid_drinks = Drinks.objects.filter(id__in=drink_ids).exclude(beer_id__in=beers_from_others)
                        spot.drinks.add(*valid_drinks)
                        
                    # Seul le créateur original peut gérer qui a accès au point
                    if request.user == spot.user:
                        old_friends = list(spot.friends.values_list('id', flat=True))
                        spot.friends.set(friend_ids)
                        # Notifier uniquement les NOUVEAUX amis ajoutés sur ce point
                        new_friends = [f for f in spot.friends.values_list('id', flat=True) if f not in old_friends]
                        notifications_invites = [
                            Notification(recipient_id=f_id, sender=request.user, notif_type='spot_invite', spot=spot)
                            for f_id in new_friends
                        ]
                        Notification.objects.bulk_create(notifications_invites)
                            
                    # Identifier tous les utilisateurs concernés (le créateur + les amis du spot)
                    users_to_notify = set(spot.friends.values_list('id', flat=True))
                    users_to_notify.add(spot.user.id)
                    
                    # Retirer celui qui fait l'action pour ne pas s'auto-notifier
                    users_to_notify.discard(request.user.id)
                    
                    # Retirer les "nouveaux" amis ajoutés lors de cette modif (ils reçoivent déjà l'invitation)
                    if request.user == spot.user and 'new_friends' in locals():
                        for nf_id in new_friends:
                            users_to_notify.discard(nf_id)
                            
                    # Envoyer les notifications
                    notifications_updates = [
                        Notification(recipient_id=u_id, sender=request.user, notif_type='spot_updated', spot=spot)
                        for u_id in users_to_notify
                    ]
                    Notification.objects.bulk_create(notifications_updates)
                        
                    messages.success(request, "Point modifié avec succès !")
                else:
                    messages.error(request, "Action non autorisée.")
            else:
                # --- MODE CRÉATION ---
                spot = BeerSpot.objects.create(
                    user=request.user,
                    title=title,
                    description=description,
                    date=date_spot,
                    latitude=float(lat),
                    longitude=float(lng)
                )
                if drink_ids:
                    spot.drinks.set(drink_ids)
                if friend_ids:
                    spot.friends.set(friend_ids)
                    notifications_invites = [
                        Notification(recipient_id=f_id, sender=request.user, notif_type='spot_invite', spot=spot)
                        for f_id in friend_ids
                    ]
                    Notification.objects.bulk_create(notifications_invites)
                    
                messages.success(request, "Point ajouté avec succès !")
                
        check_and_notify_achievements(request.user)
        return redirect('map')

    # Récupérer : Mes propres lieux + Les lieux où je suis tagué comme ami
    user_spots = BeerSpot.objects.filter(
        Q(user=request.user) | Q(friends=request.user)
    ).exclude(user__in=get_excluded_users(request.user)).distinct().prefetch_related('drinks', 'drinks__beer_id', 'friends')

    context = {
        'user_drinks': user_drinks,
        'user_spots': user_spots,
        'followers': followers,
    }
    return render(request, 'map.html', context)

@login_required(login_url='login')
def delete_spot_view(request, spot_id):
    """Permet au propriétaire de supprimer son spot sur la carte."""
    spot = get_object_or_404(BeerSpot, id=spot_id, user=request.user)
    if request.method == 'POST':
        spot.delete()
        messages.success(request, "Lieu supprimé de la carte.")
    return redirect('map')