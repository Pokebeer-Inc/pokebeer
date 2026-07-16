from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Avg, Count, Max, Q
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm

from ..models import BeerUser, UserFollow, Beer, Drinks, UserBlock
from ..forms import UserUpdateForm
from .utils import get_user_achievements

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
    my_added_beers = Beer.objects.filter(added_by=user, is_deleted=False).annotate(
        user_note=Max('drinks__note', filter=Q(drinks__drinker_id=user))
    ).order_by('-id')
    
    # Les bières retirées du catalogue
    my_deleted_beers = Beer.objects.filter(added_by=user, is_deleted=True).annotate(
        user_note=Max('drinks__note', filter=Q(drinks__drinker_id=user))
    ).order_by('-id')
    
    # Les commentaires des AUTRES sur MES bières
    feedback_on_my_beers = Drinks.objects.filter(beer_id__added_by=user).exclude(drinker_id=user).select_related('drinker_id', 'beer_id').order_by('-date')

    # Social
    followers = UserFollow.objects.filter(followed=user).select_related('follower')
    following = UserFollow.objects.filter(follower=user).select_related('followed')

    # 3. Calcul des Statistiques
    # On crée une requête spécifique pour les stats qui ignore les bières supprimées
    stats_drinks = my_drinks.filter(beer_id__is_deleted=False)
    
    last_month = timezone.now().date() - timedelta(days=30)
    total_drinks = stats_drinks.count()
    drinks_last_month = stats_drinks.filter(date__gte=last_month).count()

    averages = stats_drinks.aggregate(
        avg_note=Avg('note'),
        avg_abv=Avg('beer_id__degree'),
        avg_ibu=Avg('beer_id__bitterness')
    )

    # Calcul du style, degré et IBU préférés (basé sur les notes >= 7)
    loved_drinks = stats_drinks.filter(note__gte=7)
    
    pref_style = loved_drinks.exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values('beer_id__style').annotate(c=Count('id')).order_by('-c').first()
    
    # Préparation du Top 3
    top_beers_data = []
    for slot, beer in enumerate([user.top_beer_1, user.top_beer_2, user.top_beer_3], start=1):
        # On recherche la note attribuée par l'utilisateur pour cette bière
        drink = next((d for d in my_drinks if d.beer_id_id == beer.id), None) if beer else None
        top_beers_data.append({
            'slot': slot,
            'beer': beer,
            'note': drink.note if drink else None
        })
        
    # Récupération des trophées débloqués
    all_achievements = get_user_achievements(user)
    unlocked_achievements = [a for a in all_achievements if a['tier_level'] > 0]
        
    context = {
        'profile_form': profile_form,
        'password_form': password_form,
        'my_drinks': my_drinks,
        'my_added_beers': my_added_beers,
        'my_deleted_beers': my_deleted_beers,
        'feedback_on_my_beers': feedback_on_my_beers,
        'followers': followers,
        'following': following,
        # Stats
        'total_drinks': total_drinks,
        'drinks_last_month': drinks_last_month,
        'avg_note': averages['avg_note'] or 0,
        'avg_abv': averages['avg_abv'] or 0,
        'avg_ibu': averages['avg_ibu'] or 0,
        'pref_style': pref_style['beer_id__style'] if pref_style else "Pas encore défini",
        'top_beers_data': top_beers_data,
        'unlocked_achievements': unlocked_achievements,
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
        
    profile_user = get_object_or_404(BeerUser, username=username)
    
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

    # Calcul des Statistiques (même logique que le compte privé)
    stats_drinks = user_drinks.filter(beer_id__is_deleted=False)
    
    last_month = timezone.now().date() - timedelta(days=30)
    total_drinks = stats_drinks.count()
    drinks_last_month = stats_drinks.filter(date__gte=last_month).count()

    averages = stats_drinks.aggregate(
        avg_note=Avg('note'),
        avg_abv=Avg('beer_id__degree'),
        avg_ibu=Avg('beer_id__bitterness')
    )

    loved_drinks = stats_drinks.filter(note__gte=7)
    pref_style = loved_drinks.exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values('beer_id__style').annotate(c=Count('id')).order_by('-c').first()
    
    # Préparation du Top 3 (on ne garde que les remplis)
    top_beers_data = []
    for beer in [profile_user.top_beer_1, profile_user.top_beer_2, profile_user.top_beer_3]:
        if beer:
            drink = next((d for d in user_drinks if d.beer_id_id == beer.id), None)
            top_beers_data.append({
                'beer': beer,
                'note': drink.note if drink else None
            })
            
    all_achievements = get_user_achievements(profile_user)
    unlocked_achievements = [a for a in all_achievements if a['tier_level'] > 0]
            
    context = {
        'profile_user': profile_user,
        'user_drinks': user_drinks,
        'user_added_beers': user_added_beers,
        'followers': followers,
        'following': following,
        'is_following': is_following,
        'total_drinks': total_drinks,
        'drinks_last_month': drinks_last_month,
        'avg_note': averages['avg_note'] or 0,
        'avg_abv': averages['avg_abv'] or 0,
        'avg_ibu': averages['avg_ibu'] or 0,
        'pref_style': pref_style['beer_id__style'] if pref_style else "Inconnu",
        'top_beers_data': top_beers_data,
        'unlocked_achievements': unlocked_achievements,
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
            messages.success(request, f"Vous suivez maintenant {username} !")
            
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