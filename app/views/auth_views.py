from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from ..forms import UserRegisterForm, UserLoginForm, UserUpdateForm
from django.db.models import Avg, Count, Max, Q
from datetime import timedelta
from django.utils import timezone
from ..models import UserFollow, Beer, Drinks
from django.views.decorators.http import require_POST
import json
from django.http import JsonResponse
from .utils import get_user_achievements

def register_view(request):
    """Handles user registration."""
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, f"Bienvenue, {user.username} ! Votre compte a été créé.")
            return redirect('index')
        else:
            messages.error(request, "Erreur lors de l'inscription. Vérifiez les champs.")
    else:
        form = UserRegisterForm()

    return render(request, 'register.html', {'form': form})


def login_view(request):
    """Handles user login."""
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            next_url = request.GET.get('next', 'index')
            messages.info(request, f"Ravi de vous revoir, {user.username} !")
            return redirect(next_url)
        else:
            messages.error(request, "Nom d'utilisateur ou mot de passe incorrect.")
    else:
        form = UserLoginForm()

    return render(request, 'login.html', {'form': form})


@login_required(login_url='login')
def logout_view(request):
    logout(request)
    messages.info(request, "Vous avez été déconnecté.")
    return redirect('login')


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