import logging

from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import NON_FIELD_ERRORS
from django.db import transaction
from django.utils.http import url_has_allowed_host_and_scheme

from ..forms import UserRegisterForm, UserLoginForm, ProUserForm
from ..models import BeerUser
from ..services import claims
from ..services.places import PLACE_KINDS_BY_KEY
from ..services.welcome import send_welcome
from ..services.throttle import PRO_SIGNUP_BY_IP, SIGNUP_BY_IP
from .utils import limit_posts

logger = logging.getLogger(__name__)

@limit_posts(SIGNUP_BY_IP)
def register_view(request):
    """Handles user registration."""
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            send_welcome(user)
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
            next_url = request.GET.get('next')
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                next_url = 'index'
            messages.info(request, f"Ravi de vous revoir, {user.username} !")
            return redirect(next_url)
        elif form.has_error(NON_FIELD_ERRORS, 'throttled'):
            messages.error(request, form.throttled_message)
        elif form.has_error(NON_FIELD_ERRORS, 'inactive'):
            messages.error(request, form.error_messages['inactive'])
        else:
            messages.error(request, "Nom d'utilisateur ou mot de passe incorrect.")
    else:
        form = UserLoginForm()

    return render(request, 'login.html', {'form': form})


@login_required(login_url='login')
def logout_view(request):
    # L'appareil ne doit plus recevoir les notifications de ce compte une fois déconnecté
    BeerUser.objects.filter(pk=request.user.pk).update(fcm_token=None)
    logout(request)
    messages.info(request, "Vous avez été déconnecté.")
    return redirect('login')

def _register_pending_manager(kind, user_form, pro_form, plan):
    """Crée le compte et sa demande de gestion, ensemble ou pas du tout. Le membre n'est PAS ajouté aux gérants : l'équipe valide d'abord.

    Fiche existante (`plan.place`) : la demande porte sur elle. Sinon la fiche est créée, sans SIRET (il reste sur la demande jusqu'à
    l'acceptation, pour qu'on ne puisse pas « réserver » le SIRET d'un autre)."""
    with transaction.atomic():
        user = user_form.save()
        place = plan.place
        if place is None:
            place = pro_form.save(commit=False)
            place.siret = None
            if hasattr(place, 'added_by'):
                place.added_by = user
            place.save()
        claims.open_claim(user, kind, place, pro_form.cleaned_data['siret'], check=plan.check)
    return user, place


@limit_posts(PRO_SIGNUP_BY_IP)
def register_pro_view(request, pro_type):
    kind = PLACE_KINDS_BY_KEY.get(pro_type)
    if kind is None:  # sécurité : seuls les types connus
        return redirect('register')

    claim_report = None
    if request.method == 'POST':
        user_form = ProUserForm(request.POST, prefix='user')
        pro_form = kind.pro_form(request.POST, request.FILES, prefix='pro')

        if user_form.is_valid() and pro_form.is_valid():
            data = pro_form.cleaned_data
            try:
                plan = claims.plan_registration(kind, data['name'], data['postal_code'], data['city'], data['siret'], request.POST.get('pro-claim_choice', ''))
                user, place = _register_pending_manager(kind, user_form, pro_form, plan)
            except claims.ChoiceRequired as choice:
                claim_report = choice.report
                messages.warning(request, "Des fiches existent déjà avec ce nom : indiquez laquelle est la vôtre.")
            except claims.ClaimError as error:
                pro_form.add_error(error.field if error.field in pro_form.fields else None, str(error))
                messages.error(request, str(error))
            except Exception:
                logger.exception("Inscription d'un gérant impossible")
                messages.error(request, "Erreur lors de la création. Réessayez plus tard.")
            else:
                send_welcome(user)
                messages.success(request, f"Compte créé. Votre demande de gestion de {place.name} est en cours d'examen : vous recevrez la réponse par e-mail et par notification. Connectez-vous.")
                return redirect('login')
        else:
            messages.error(request, "Veuillez corriger les erreurs dans le formulaire.")
    else:
        user_form = ProUserForm(prefix='user')
        pro_form = kind.pro_form(prefix='pro')

    return render(request, 'register_pro.html', {'user_form': user_form, 'pro_form': pro_form, 'pro_type': pro_type, 'claim_report': claim_report})
