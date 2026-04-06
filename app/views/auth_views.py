from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from ..forms import UserRegisterForm, UserLoginForm, UserUpdateForm
from django.db.models import Avg, Count, Max, Q
from datetime import timedelta
from django.utils import timezone
from ..models import BeerUser, UserFollow, Beer, Drinks

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
    my_added_beers = Beer.objects.filter(added_by=user).annotate(
        user_note=Max('drinks__note', filter=Q(drinks__drinker_id=user))
    ).order_by('-id')
    
    # Les commentaires des AUTRES sur MES bières
    feedback_on_my_beers = Drinks.objects.filter(beer_id__added_by=user).exclude(drinker_id=user).select_related('drinker_id', 'beer_id').order_by('-date')

    # Social
    followers = UserFollow.objects.filter(followed=user).select_related('follower')
    following = UserFollow.objects.filter(follower=user).select_related('followed')

    # 3. Calcul des Statistiques
    last_month = timezone.now().date() - timedelta(days=30)
    total_drinks = my_drinks.count()
    drinks_last_month = my_drinks.filter(date__gte=last_month).count()

    averages = my_drinks.aggregate(
        avg_note=Avg('note'),
        avg_abv=Avg('beer_id__degree'),
        avg_ibu=Avg('beer_id__bitterness')
    )

    # Calcul du style, degré et IBU préférés (basé sur les notes >= 7)
    loved_drinks = my_drinks.filter(note__gte=7)
    
    pref_style = loved_drinks.exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values('beer_id__style').annotate(c=Count('id')).order_by('-c').first()
    
    context = {
        'profile_form': profile_form,
        'password_form': password_form,
        'my_drinks': my_drinks,
        'my_added_beers': my_added_beers,
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
    }
    return render(request, 'account.html', context)

@login_required(login_url='login')
def public_profile_view(request, username):
    """Affiche le profil public d'un autre utilisateur."""
    # Si l'utilisateur clique sur son propre profil, on le redirige vers son compte privé
    if request.user.username == username:
        return redirect('account')
        
    profile_user = get_object_or_404(BeerUser, username=username)
    
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
    last_month = timezone.now().date() - timedelta(days=30)
    total_drinks = user_drinks.count()
    drinks_last_month = user_drinks.filter(date__gte=last_month).count()

    averages = user_drinks.aggregate(
        avg_note=Avg('note'),
        avg_abv=Avg('beer_id__degree'),
        avg_ibu=Avg('beer_id__bitterness')
    )

    loved_drinks = user_drinks.filter(note__gte=7)
    pref_style = loved_drinks.exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values('beer_id__style').annotate(c=Count('id')).order_by('-c').first()
    
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
            
    return redirect('public_profile', username=username)