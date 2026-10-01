from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone

from ..models import BeerUser, Drinks, BeerSpot, UserFollow, Notification, Bar, Brewery
from ..forms import BeerSpotForm, error_summary
from .utils import get_excluded_users, check_and_notify_achievements
from ..services.realtime_service import broadcast_notifications

def _participant_drinks(spot, drink_slugs):
    """Restreint les dégustations à celles du créateur du lieu et de ses amis invités."""
    participants = Q(drinker_id=spot.user) | Q(drinker_id__in=spot.friends.all())
    return Drinks.objects.filter(participants, slug__in=drink_slugs)

def _invitable_friends(usernames):
    """Ne garde que les comptes actifs parmi les amis invités (désignés par leur pseudo) et renvoie leurs clés internes."""
    return list(BeerUser.objects.filter(username__in=usernames, is_active=True).values_list('id', flat=True))

@login_required(login_url='login')
def map_view(request):
    # Les abonnés de l'utilisateur (les gens qui LE suivent)
    followers = UserFollow.objects.filter(followed=request.user, follower__is_active=True).select_related('follower')
    
    # Ses dégustations
    user_drinks = Drinks.objects.filter(drinker_id=request.user).select_related('beer_id').order_by('-date')
    
    if request.method == 'POST':
        form = BeerSpotForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Le point n'a pas pu être enregistré : " + " ; ".join(error_summary(form)))
            return redirect('map')

        spot_slug = form.cleaned_data['spot_slug'] # S'il y a un slug, c'est une modification
        title = form.cleaned_data['title']
        description = form.cleaned_data['description']
        date_spot = form.cleaned_data['date'] or timezone.now().date()
        lat = form.cleaned_data['lat']
        lng = form.cleaned_data['lng']
        drink_slugs = request.POST.getlist('drinks')
        friend_ids = _invitable_friends(request.POST.getlist('friends'))
        
        if spot_slug:
            # --- MODE MODIFICATION ---
            spot = get_object_or_404(BeerSpot, slug=spot_slug)
            
            # Vérification des droits : Créateur OU Ami associé
            if request.user == spot.user or request.user in spot.friends.all():
                spot.title = title
                spot.description = description
                spot.date = date_spot
                spot.latitude = lat
                spot.longitude = lng
                spot.save()
                
                user_current_drinks = spot.drinks.filter(drinker_id=request.user)
                spot.drinks.remove(*user_current_drinks)
                if drink_slugs:
                    # On identifie les bières déjà ajoutées par les autres sur ce point
                    beers_from_others = spot.drinks.exclude(drinker_id=request.user).values_list('beer_id', flat=True)
                    # On ne garde que les dégustations dont la bière n'est pas déjà présente
                    valid_drinks = _participant_drinks(spot, drink_slugs).exclude(beer_id__in=beers_from_others)
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
                    created_invites = Notification.objects.bulk_create(notifications_invites)
                    broadcast_notifications(created_invites)
                        
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
                created_updates = Notification.objects.bulk_create(notifications_updates)
                broadcast_notifications(created_updates)
                    
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
                latitude=lat,
                longitude=lng
            )
            if friend_ids:
                spot.friends.set(friend_ids)
                notifications_invites = [
                    Notification(recipient_id=f_id, sender=request.user, notif_type='spot_invite', spot=spot)
                    for f_id in friend_ids
                ]
                created_invites = Notification.objects.bulk_create(notifications_invites)
                broadcast_notifications(created_invites)
            if drink_slugs:
                spot.drinks.set(_participant_drinks(spot, drink_slugs))
                
            messages.success(request, "Point ajouté avec succès !")
                
        check_and_notify_achievements(request.user)
        return redirect('map')

    # Récupérer : Mes propres lieux + Les lieux où je suis tagué comme ami
    user_spots = BeerSpot.objects.filter(
        Q(user=request.user) | Q(friends=request.user)
    ).exclude(user__in=get_excluded_users(request.user)).distinct().prefetch_related('drinks', 'drinks__beer_id', 'friends')
    
    # Afficher les bars et les brasseries
    bars = Bar.objects.filter(latitude__isnull=False, longitude__isnull=False)
    breweries = Brewery.objects.filter(latitude__isnull=False, longitude__isnull=False)

    context = {
        'user_drinks': user_drinks,
        'user_spots': user_spots,
        'followers': followers,
        'bars': bars,
        'breweries': breweries,
    }
    return render(request, 'map.html', context)

@login_required(login_url='login')
def delete_spot_view(request, spot_slug):
    """Permet au propriétaire de supprimer son spot sur la carte."""
    spot = get_object_or_404(BeerSpot, slug=spot_slug, user=request.user)
    if request.method == 'POST':
        spot.delete()
        messages.success(request, "Lieu supprimé de la carte.")
    return redirect('map')