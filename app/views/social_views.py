from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import Max, Q
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
import json

from ..models import BeerUser, UserFollow, Beer, Drinks, UserBlock, Notification, DrinkReaction
from ..forms import UserUpdateForm, DrinkForm
from .utils import get_user_achievements, check_and_notify_achievements
from .services.stats import get_user_statistics, get_top_beers_data
from .services.selectors import get_filtered_beers
from ..services.realtime_service import broadcast_notifications

@login_required(login_url='login')
def account_view(request):
    """Gère le profil ET le changement de mot de passe sur la même page."""
    user = request.user
    profile_form = UserUpdateForm(instance=user)
    password_form = PasswordChangeForm(user=user)
    
    if request.method == 'POST':
        if 'btn_profile' in request.POST:
            profile_form = UserUpdateForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                
                check_and_notify_achievements(request.user)
                
                messages.success(request, "Profil mis à jour.")
                return redirect('account')

        elif 'btn_password' in request.POST:
            password_form = PasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Votre mot de passe a été changé avec succès !")
                return redirect('account')
            else:
                messages.error(request, "Erreur dans le changement de mot de passe.")

    # 2. Requêtes de base
    my_drinks = Drinks.objects.filter(drinker_id=user).select_related('beer_id', 'beer_id__brewery_id').order_by('-date')
    
    # Social
    followers = UserFollow.objects.filter(followed=user).select_related('follower')
    following = UserFollow.objects.filter(follower=user).select_related('followed')

    # 3. Calcul des Statistiques
    stats = get_user_statistics(my_drinks)
    top_beers_data = get_top_beers_data(user, my_drinks, include_empty=True)
        
    # Récupération des trophées débloqués
    all_achievements = get_user_achievements(user)
    unlocked_achievements = [a for a in all_achievements if a['tier_level'] > 0]
        
    context = {
        'profile_form': profile_form,
        'password_form': password_form,
        'my_drinks': my_drinks,
        'followers': followers,
        'following': following,
        'top_beers_data': top_beers_data,
        'unlocked_achievements': unlocked_achievements,
        **stats
    }
    return render(request, 'account.html', context)

@login_required(login_url='login')
def delete_account_view(request):
    """Supprime le compte de l'utilisateur et ses données associées (sauf les bières du catalogue)."""
    if request.method == 'POST':
        user = request.user
        # 1. On déconnecte l'utilisateur pour invalider sa session
        logout(request)
        # 2. On supprime l'utilisateur (Django gère les CASCADE et les SET_NULL automatiquement)
        user.delete()
        
        messages.success(request, "Votre compte et toutes vos données personnelles ont été supprimés. Au revoir !")
        return redirect('index')
        
    return redirect('account')

@login_required(login_url='login')
def public_profile_view(request, username):
    """Affiche le profil public d'un autre utilisateur."""
    # Si l'utilisateur clique sur son propre profil, on le redirige vers son compte privé
    if request.user.username == username:
        return redirect('account')
        
    profile_user = get_object_or_404(
        BeerUser.objects.select_related('top_beer_1', 'top_beer_2', 'top_beer_3'), 
        username=username
    )
    
    # Vérification blocage mutuel
    if UserBlock.objects.filter(Q(blocker=request.user, blocked=profile_user) | 
                                Q(blocker=profile_user, blocked=request.user)).exists():
        messages.error(request, "Ce profil n'est pas accessible.")
        return redirect('index')
    
    # Requêtes de base pour cet utilisateur
    user_drinks = Drinks.objects.filter(drinker_id=profile_user).select_related('beer_id', 'beer_id__brewery_id').order_by('-date')
    user_added_beers = Beer.objects.filter(added_by=profile_user).annotate(
        user_note=Max('drinks__note', filter=Q(drinks__drinker_id=profile_user))
    ).order_by('-id')
    
    # Social
    followers = UserFollow.objects.filter(followed=profile_user).select_related('follower')
    following = UserFollow.objects.filter(follower=profile_user).select_related('followed')
    
    # Est-ce que JE (l'utilisateur connecté) suis cette personne ?
    is_following = followers.filter(follower=request.user).exists()

    # Calcul des Statistiques
    stats = get_user_statistics(user_drinks)
    top_beers_data = get_top_beers_data(profile_user, user_drinks, include_empty=False)
            
    all_achievements = get_user_achievements(profile_user)
    unlocked_achievements = [a for a in all_achievements if a['tier_level'] > 0]
            
    context = {
        'profile_user': profile_user,
        'user_drinks': user_drinks,
        'user_added_beers': user_added_beers,
        'followers': followers,
        'following': following,
        'is_following': is_following,
        'top_beers_data': top_beers_data,
        'unlocked_achievements': unlocked_achievements,
        **stats
    }
    return render(request, 'public_profile.html', context)

@login_required(login_url='login')
def follow_user(request, username):
    """Gère l'action de s'abonner ou se désabonner."""
    user_to_follow = get_object_or_404(BeerUser, username=username)
    
    if request.user != user_to_follow:
        follow_record = UserFollow.objects.filter(follower=request.user, followed=user_to_follow)
        if follow_record.exists():
            follow_record.delete() # Se désabonner
            messages.info(request, f"Vous ne suivez plus {username}.")
        else:
            UserFollow.objects.create(follower=request.user, followed=user_to_follow) # S'abonner
            notif = Notification.objects.create(recipient=user_to_follow, sender=request.user, notif_type='follow')
            broadcast_notifications([notif])
            messages.success(request, f"Vous suivez maintenant {username} !")
            
    check_and_notify_achievements(request.user)
    return redirect(request.META.get('HTTP_REFERER', 'index'))

@login_required(login_url='login')
def remove_follower(request, username):
    """Permet à un utilisateur de supprimer quelqu'un de ses abonnés."""
    follower_to_remove = get_object_or_404(BeerUser, username=username)
    
    # On cherche le lien où follower_to_remove suit request.user
    follow_record = UserFollow.objects.filter(follower=follower_to_remove, followed=request.user)
    
    if request.method == 'POST' and follow_record.exists():
        follow_record.delete()
        messages.info(request, f"{username} a été retiré de vos abonnés.")
        
    return redirect(request.META.get('HTTP_REFERER', 'account'))

@require_POST
@login_required(login_url='login')
def toggle_reaction_view(request, drink_id):
    """API pour liker/disliker un avis."""
    try:
        data = json.loads(request.body)
        is_like = data.get('is_like')
        
        drink = get_object_or_404(Drinks, id=drink_id)
        if drink.drinker_id == request.user:
            return JsonResponse({'success': False, 'error': "Vous ne pouvez pas réagir à votre propre avis."}, status=400)
            
        reaction, created = DrinkReaction.objects.get_or_create(
            user=request.user, 
            drink=drink, 
            defaults={'is_like': is_like}
        )
        
        current_reaction = is_like # On garde en mémoire l'état final
        
        # Logique : Bascule si déjà existant
        if not created:
            if reaction.is_like == is_like:
                reaction.delete() # Clic sur le même bouton = annulation
                current_reaction = None
            else:
                reaction.is_like = is_like
                reaction.save() # Changement d'avis (ex: passe de Like à Dislike)
                
                if is_like:
                    notif = Notification.objects.create(
                        recipient=drink.drinker_id, 
                        sender=request.user, 
                        notif_type='drink_liked', 
                        beer=drink.beer_id
                    )
                    broadcast_notifications([notif])
        else:
            # Notification si c'est une nouvelle réaction et que c'est un Like
            if is_like:
                notif = Notification.objects.create(
                    recipient=drink.drinker_id, 
                    sender=request.user, 
                    notif_type='drink_liked', 
                    beer=drink.beer_id
                )
                broadcast_notifications([notif])
        
        # Vérification du trophée César
        check_and_notify_achievements(request.user)
        
        # Recalcul des scores exacts
        likes = drink.reactions.filter(is_like=True).count()
        dislikes = drink.reactions.filter(is_like=False).count()
        
        return JsonResponse({
            'success': True,
            'score': likes - dislikes,
            'likes': likes,
            'dislikes': dislikes,
            'current_reaction': current_reaction
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

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

@require_POST
@login_required(login_url='login')
def toggle_wishlist(request, beer_id):
    """API pour ajouter/retirer une bière de la wishlist."""
    beer = get_object_or_404(Beer, id=beer_id)
    user = request.user
    
    if beer in user.wishlist_beers.all():
        user.wishlist_beers.remove(beer)
        is_in_wishlist = False
    else:
        user.wishlist_beers.add(beer)
        is_in_wishlist = True
        
        # Notification au créateur de la bière
        if beer.added_by and beer.added_by != user:
            notif = Notification.objects.create(
                recipient=beer.added_by,
                sender=user,
                notif_type='wishlist_added',
                beer=beer
            )
            broadcast_notifications([notif])
        
    return JsonResponse({'success': True, 'is_in_wishlist': is_in_wishlist})

@login_required(login_url='login')
def wishlist_view(request):
    """Page affichant la wishlist de l'utilisateur."""
    # On réutilise le helper de filtrage des bières en restreignant à la wishlist
    beers = get_filtered_beers(request).filter(wishlisted_by=request.user)[:10]
    
    # Récupération des styles présents UNIQUEMENT dans les bières de la wishlist
    styles = request.user.wishlist_beers.exclude(style__isnull=True).exclude(style='').values_list('style', flat=True).distinct().order_by('style')
    
    rating_form = DrinkForm()
    
    # Optimisation des annotations (notes et wishlist) sur l'affichage actuel
    displayed_ids = [b.id for b in beers]
    rated_beer_ids = list(Drinks.objects.filter(drinker_id=request.user, beer_id__in=displayed_ids).values_list('beer_id', flat=True))
    wishlist_beer_ids = list(request.user.wishlist_beers.filter(id__in=displayed_ids).values_list('id', flat=True))

    context = {
        'beers': beers,
        'styles': styles,
        'rating_form': rating_form,
        'rated_beer_ids': rated_beer_ids,
        'wishlist_beer_ids': wishlist_beer_ids,
    }
    return render(request, 'wishlist.html', context)

@login_required(login_url='login')
def achievements_view(request):
    """Page des trophées, hauts faits et cosmétiques."""
    achievements = get_user_achievements(request.user)
    return render(request, 'achievements.html', {'achievements': achievements})