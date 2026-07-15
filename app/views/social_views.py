from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Avg, Count, Max, Q
from datetime import timedelta
from django.utils import timezone
from ..models import BeerUser, UserFollow, Beer, Drinks, UserBlock

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