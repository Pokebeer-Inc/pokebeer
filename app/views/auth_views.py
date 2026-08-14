from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction

from ..forms import UserRegisterForm, UserLoginForm, ProUserForm, BarProForm, BreweryProForm

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

def register_pro_view(request, pro_type):
    # Sécurité : n'accepte que ces deux types
    if pro_type not in ['bar', 'brewery']:
        return redirect('register')

    if request.method == 'POST':
        user_form = ProUserForm(request.POST, prefix='user')
        if pro_type == 'bar':
            pro_form = BarProForm(request.POST, request.FILES, prefix='pro')
        else:
            pro_form = BreweryProForm(request.POST, request.FILES, prefix='pro')

        if user_form.is_valid() and pro_form.is_valid():
            try:
                # La transaction atomique garantit que tout est sauvegardé en même temps, ou rien du tout.
                with transaction.atomic():
                    # 1. Création du compte utilisateur (Manager)
                    user = user_form.save(commit=False)
                    user.set_password(user_form.cleaned_data['password']) # Hashage sécurisé
                    user.save()

                    # 2. Création de l'établissement lié
                    pro_instance = pro_form.save(commit=False)
                    
                    # On garde la trace du créateur initial
                    if pro_type == 'bar':
                        pro_instance.added_by = user 
                    elif pro_type == 'brewery':
                        # Si tu as ajouté un added_by à Brewery aussi, tu peux le mettre ici
                        pass 
                    
                    # Il faut d'abord sauvegarder l'instance pour générer son ID
                    pro_instance.save()
                    
                    # 3. On ajoute l'utilisateur à la liste des gérants (droits de modification futurs)
                    pro_instance.managers.add(user)
                    
                messages.success(request, f"L'établissement {pro_instance.name} a été créé ! Connectez-vous.")
                return redirect('login')
                
            except Exception as e:
                messages.error(request, f"Erreur lors de la création : {e}")
        else:
            messages.error(request, "Veuillez corriger les erreurs dans le formulaire.")
    else:
        user_form = ProUserForm(prefix='user')
        pro_form = BarProForm(prefix='pro') if pro_type == 'bar' else BreweryProForm(prefix='pro')

    context = {
        'user_form': user_form,
        'pro_form': pro_form,
        'pro_type': pro_type,
    }
    return render(request, 'register_pro.html', context)