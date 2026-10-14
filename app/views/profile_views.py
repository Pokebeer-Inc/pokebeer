"""Profil public d'un membre, abonnements, Top 3 et trophées."""
from django.contrib import messages
from django.db.models import Count, Max, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from urllib.parse import urlsplit
import json

from ..models import Beer, BeerUser, Drinks, UserFollow
from ..services.members import social
from ..services.members.achievements import get_user_achievements
from ..services.members.follows import follow_context
from ..services.members.profile_stats import get_top_beers_data, get_user_statistics
from ..services.members.visibility import is_blocked_between
from .utils import chosen_tab, previous_page

PROFILE_TABS = ('tastings', 'additions')
PROFILE_TAB_ALIASES = {'degustations': 'tastings', 'ajouts': 'additions'}  # anciens noms français

def public_profile_view(request, username):
    """Affiche le profil public d'un autre utilisateur."""
    # Si l'utilisateur clique sur son propre profil, on le redirige vers son compte privé
    if request.user.username == username:
        return redirect('account')
        
    profile_user = get_object_or_404(
        BeerUser.objects.filter(is_active=True).select_related('top_beer_1', 'top_beer_2', 'top_beer_3'), 
        username=username
    )
    
    # Vérification blocage mutuel
    if is_blocked_between(request.user, profile_user):
        messages.error(request, "Ce profil n'est pas accessible.")
        return redirect('index')
    
    # Toutes les dégustations servent aux statistiques ; seule la liste de l'onglet affiché est chargée (10 premières)
    user_drinks = Drinks.objects.filter(drinker=profile_user).select_related('beer', 'beer__brewery').order_by('-date')

    active_tab = chosen_tab(request.GET.get('tab'), PROFILE_TABS, PROFILE_TAB_ALIASES, default='tastings')
    shown_drinks, added_beers = [], []
    if active_tab == 'tastings':
        shown_drinks = list(user_drinks[:10])
    else:
        added_beers = list(Beer.objects.filter(added_by=profile_user, is_deleted=False).annotate(
            user_note=Max('drinks__note', filter=Q(drinks__drinker=profile_user)),
            count_rating=Count('drinks')
        ).order_by('-id')[:10])

    # Est-ce que JE (l'utilisateur connecté) suis cette personne ?
    is_following = UserFollow.objects.filter(followed=profile_user, follower=request.user).exists()

    # Calcul des Statistiques
    stats = get_user_statistics(user_drinks)
    top_beers_data = get_top_beers_data(profile_user, user_drinks, include_empty=False)

    all_achievements, level_data = get_user_achievements(profile_user)
    unlocked_achievements = [a for a in all_achievements if a['tier_level'] > 0]

    # Retour vers la page d'origine ; si c'est ce profil lui-même (rechargé par les puces), vers la recherche
    back_url = previous_page(request)
    if urlsplit(back_url).path == request.path:
        back_url = reverse('index')

    show_establishments = profile_user.has_public_establishments
    context = {
        'profile_user': profile_user,
        'active_tab': active_tab,
        'user_drinks': shown_drinks,
        'user_added_beers': added_beers,
        **follow_context(profile_user),
        'is_following': is_following,
        'top_beers_data': top_beers_data,
        'unlocked_achievements': unlocked_achievements,
        'level': level_data['current_level'],
        'show_establishments': show_establishments,
        'managed_breweries': list(profile_user.my_breweries) if show_establishments else [],
        'managed_bars': list(profile_user.my_bars) if show_establishments else [],
        'back_url': back_url,
        **stats
    }
    return render(request, 'public_profile.html', context)

@require_POST
def follow_user(request, username):
    """Gère l'action de s'abonner ou se désabonner."""
    user_to_follow = get_object_or_404(BeerUser, username=username, is_active=True)
    try:
        following = social.toggle_follow(request.user, user_to_follow)
    except social.Unreachable:
        raise Http404 from None  # même réponse qu'un profil inexistant : on ne révèle pas qui a bloqué qui
    if user_to_follow != request.user:
        if following:
            messages.success(request, f"Vous suivez maintenant {username} !")
        else:
            messages.info(request, f"Vous ne suivez plus {username}.")
    return redirect(previous_page(request))


@require_POST
def remove_follower(request, username):
    """Permet à un utilisateur de supprimer quelqu'un de ses abonnés."""
    follower = get_object_or_404(BeerUser, username=username)
    if social.remove_follower(request.user, follower):
        messages.info(request, f"{username} a été retiré de vos abonnés.")
    return redirect(previous_page(request, 'account'))


@require_POST
def update_top_beer(request, slot):
    """Met à jour l'un des 3 slots du Top 3 de l'utilisateur."""
    if slot not in [1, 2, 3]:
        messages.error(request, "Emplacement invalide.")
        return redirect('account')

    beer_slug = request.POST.get('beer_slug')
    user = request.user

    if beer_slug:
        # Seules les bières du catalogue que le membre a dégustées peuvent entrer dans son top (c'est ce que propose la fenêtre de choix)
        beer = get_object_or_404(Beer.objects.filter(is_deleted=False, drinks__drinker=user).distinct(), slug=beer_slug)
        
        if (slot != 1 and user.top_beer_1_id == beer.id) or \
           (slot != 2 and user.top_beer_2_id == beer.id) or \
           (slot != 3 and user.top_beer_3_id == beer.id):
            messages.error(request, f"{beer.name} est déjà dans votre Top 3 !")
            return redirect('account')

        setattr(user, f'top_beer_{slot}', beer)
        messages.success(request, f"Bière ajoutée à votre Top {slot} !")
    else:
        # Si aucun slug n'est fourni, on vide l'emplacement
        setattr(user, f'top_beer_{slot}', None)
        messages.info(request, f"Emplacement Top {slot} vidé.")

    user.save(update_fields=['top_beer_1', 'top_beer_2', 'top_beer_3'])
    return redirect('account')

@require_POST
def reorder_top_beers(request):
    """API du glisser-déposer du Top 3 : `order` donne, pour chaque position, l'ancien emplacement qui vient s'y placer.

    Ex. [2, 3, 1] : la bière du 2 passe en 1, celle du 3 en 2, celle du 1 en 3. Seule une permutation de 1, 2, 3 est acceptée.
    """
    if len(request.body) > 200:
        return JsonResponse({'success': False, 'error': 'Requête invalide'}, status=400)
    try:
        order = json.loads(request.body).get('order')
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({'success': False, 'error': 'Requête invalide'}, status=400)
    if not (isinstance(order, list) and len(order) == 3 and all(type(slot) is int for slot in order) and sorted(order) == [1, 2, 3]):
        return JsonResponse({'success': False, 'error': 'Emplacements invalides'}, status=400)

    user = request.user
    current = {1: user.top_beer_1_id, 2: user.top_beer_2_id, 3: user.top_beer_3_id}
    user.top_beer_1_id, user.top_beer_2_id, user.top_beer_3_id = (current[slot] for slot in order)
    user.save(update_fields=['top_beer_1', 'top_beer_2', 'top_beer_3'])
    return JsonResponse({'success': True})

def achievements_view(request):
    """Page des trophées, hauts faits et cosmétiques."""
    achievements, level_data = get_user_achievements(request.user)
    
    context = {
        'achievements': achievements,
        'level_data': level_data,
    }
    return render(request, 'achievements.html', context)
