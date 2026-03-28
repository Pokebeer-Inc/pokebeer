from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from ..forms import UserRegisterForm, UserLoginForm, UserUpdateForm
from ..models import Drinks

def register_view(request):
    """Handles user registration."""
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
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
    profile_form = UserUpdateForm(instance=request.user)
    password_form = PasswordChangeForm(user=request.user)
    
    if request.method == 'POST':
        if 'btn_profile' in request.POST:
            profile_form = UserUpdateForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Vos informations ont été mises à jour.")
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

    my_drinks = Drinks.objects.filter(drinker_id=request.user)\
        .select_related('beer_id', 'beer_id__brewery_id')\
        .order_by('-date', 'beer_id__name')

    context = {
        'profile_form': profile_form,
        'password_form': password_form,
        'my_drinks': my_drinks
    }
    return render(request, 'account.html', context)