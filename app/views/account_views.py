"""Compte du membre connecté : profil et réglages, pseudo, suppression du compte."""
from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
import logging

from ..forms import FeedbackForm, MarketingConsentForm, NotificationPreferenceForm, ProSettingsForm, UserUpdateForm, UsernameForm
from ..models import AccountDeletion, Drinks
from ..services.members import password_reset
from ..services.members.achievements import check_and_notify_achievements, get_user_achievements
from ..services.support.feedback import FeedbackError, open_thread
from ..services.members.follows import follow_context
from ..services.members.inactivity import delete_account
from ..services.members.profile_stats import get_top_beers_data, get_user_statistics
from ..services.protection.throttle import USERNAME_ATTEMPTS, USERNAME_CHANGES

logger = logging.getLogger(__name__)

SETTINGS_SECTIONS = {
    'profile': "Informations et bio",
    'notifications': "Notifications et e-mails",
    'privacy': "Visibilité et confidentialité",
    'security': "Mot de passe",
    'team': "Écrire à l'équipe",
}


# --- Un gestionnaire par formulaire de la page : il reçoit la requête, le membre, les formulaires de la page (qu'il remplace par la version
# liée aux données envoyées) et `done()` (redirection de succès) ; il renvoie une réponse s'il y en a une, sinon la page est réaffichée.

def _save_profile(request, user, forms, done):
    forms['profile_form'] = UserUpdateForm(request.POST, instance=user)
    if forms['profile_form'].is_valid():
        forms['profile_form'].save()
        check_and_notify_achievements(user)
        messages.success(request, "Profil mis à jour.")
        return done()


def _save_privacy(request, user, forms, done):
    forms['pro_settings_form'] = ProSettingsForm(request.POST, instance=user)
    if forms['pro_settings_form'].is_valid():
        forms['pro_settings_form'].save()
        messages.success(request, "Paramètres de confidentialité mis à jour.")
        return done()
    messages.error(request, "Erreur dans le changement de préférence de la visibilité.")


def _change_password(request, user, forms, done):
    forms['password_form'] = PasswordChangeForm(user=user, data=request.POST)
    if forms['password_form'].is_valid():
        updated = forms['password_form'].save()
        update_session_auth_hash(request, updated)
        password_reset.notify_password_changed(updated)
        messages.success(request, "Votre mot de passe a été changé avec succès !")
        return done()
    messages.error(request, "Erreur dans le changement de mot de passe.")


def _send_feedback(request, user, forms, done):
    forms['feedback_form'] = FeedbackForm(request.POST)
    if not forms['feedback_form'].is_valid():
        messages.error(request, "Erreur dans l'envoi de votre feedback.")
        return None
    try:
        thread = open_thread(user, forms['feedback_form'].cleaned_data['message'])
    except FeedbackError as error:
        messages.error(request, str(error))
        return None
    messages.success(request, "Merci ! Votre message a bien été envoyé à l'équipe.")
    return redirect('feedback_thread', feedback_slug=thread.slug)


def _save_notification_preferences(request, user, forms, done):
    forms['notif_form'] = NotificationPreferenceForm(request.POST, instance=user)
    if forms['notif_form'].is_valid():
        forms['notif_form'].save()
        messages.success(request, "Préférences de notifications mises à jour.")
        return done()
    messages.error(request, "Erreur dans le changement de préférence des notifications.")


def _save_marketing_consent(request, user, forms, done):
    forms['marketing_form'] = MarketingConsentForm(request.POST, user=user)
    if forms['marketing_form'].is_valid():
        forms['marketing_form'].save()
        messages.success(request, "Préférence d'e-mails mise à jour.")
        return done()


# Bouton envoyé -> gestionnaire ; le premier bouton présent dans la requête est traité
FORM_ACTIONS = {
    'btn_profile': _save_profile,
    'btn_pro_settings': _save_privacy,
    'btn_password': _change_password,
    'btn_feedback': _send_feedback,
    'btn_notifs': _save_notification_preferences,
    'btn_marketing': _save_marketing_consent,
}


def _profile_page_context(user, forms):
    """Contexte de la page de profil : formulaires, statistiques, Top 3, trophées, établissements gérés, abonnés."""
    my_drinks = Drinks.objects.filter(drinker=user).order_by('-date')
    all_achievements, level_data = get_user_achievements(user)
    managed_breweries = list(user.managed_breweries.all())
    managed_bars = list(user.managed_bars.all())
    return {
        **forms,
        'managed_breweries': managed_breweries,
        'managed_bars': managed_bars,
        'show_establishments_section': bool(managed_breweries or managed_bars or user.is_bartender or user.is_brewer),
        'pending_claims': user.claims.filter(status='pending').select_related('brewery', 'bar'),
        'feedback_threads_count': user.feedbacks.count(),
        # Choix des fenêtres du Top 3 : seulement les quatre colonnes affichées, pas les dégustations entières
        'top_choices': list(my_drinks.values('beer', 'beer__slug', 'beer__name', 'note')),
        **follow_context(user),
        'top_beers_data': get_top_beers_data(user, my_drinks, include_empty=True),
        'unlocked_achievements': [a for a in all_achievements if a['tier_level'] > 0],
        'level': level_data['current_level'],
        **get_user_statistics(my_drinks),
    }


@login_required(login_url='login')
def account_view(request, section=None):
    """Profil (page unique) et réglages : chaque section de réglages a sa page, avec les mêmes formulaires qu'avant."""
    if section is not None and section not in SETTINGS_SECTIONS:
        raise Http404
    user = request.user

    def done():
        return redirect('account_settings', section=section) if section else redirect('account')

    forms = {
        'profile_form': UserUpdateForm(instance=user),
        'password_form': PasswordChangeForm(user=user),
        'feedback_form': FeedbackForm(),
        'notif_form': NotificationPreferenceForm(instance=user),
        'marketing_form': MarketingConsentForm(user=user),
        'pro_settings_form': ProSettingsForm(instance=user),
    }

    if request.method == 'POST':
        button = next((name for name in FORM_ACTIONS if name in request.POST), None)
        if button:
            response = FORM_ACTIONS[button](request, user, forms, done)
            if response is not None:
                return response

    if section:
        return render(request, 'account_settings.html', {
            'section': section, 'section_title': SETTINGS_SECTIONS[section], **forms,
            'feedback_threads_count': user.feedbacks.count(),
        })
    return render(request, 'account.html', _profile_page_context(user, forms))


@login_required(login_url='login')
def delete_account_view(request):
    """Supprime le compte de l'utilisateur et ses données associées (sauf les bières du catalogue)."""
    if request.method == 'POST':
        user = request.user
        # 1. On déconnecte l'utilisateur pour invalider sa session
        logout(request)
        # 2. On supprime l'utilisateur (Django gère les CASCADE et les SET_NULL automatiquement) et on en garde la trace
        delete_account(user, AccountDeletion.Reason.SELF)
        
        messages.success(request, "Votre compte et toutes vos données personnelles ont été supprimés. Au revoir !")
        return redirect('index')
        
    return redirect('account')

@require_POST
@login_required(login_url='login')
def update_username_view(request):
    """Change le pseudo du membre connecté (l'URL de son profil public change avec lui).

    Validation côté serveur uniquement : format, unicité sans casse, pseudos réservés (UsernameForm). Deux plafonds par
    membre : les essais (pour qu'on ne puisse pas sonder les pseudos libres) et les changements réellement faits.
    Répond en JSON pour la fenêtre de la page profil, par redirection sinon.
    """
    wants_json = request.headers.get('X-Requested-With') == 'fetch'
    key = f"user:{request.user.pk}"

    def refuse(message, status):
        if wants_json:
            return JsonResponse({'success': False, 'error': message}, status=status)
        messages.error(request, message)
        return redirect('account')

    if USERNAME_ATTEMPTS.exceeded(key) or USERNAME_CHANGES.exceeded(key):
        return refuse("Trop de changements de pseudo. Réessayez plus tard.", 429)
    USERNAME_ATTEMPTS.record(key)

    form = UsernameForm(request.POST, instance=request.user)
    if not form.is_valid():
        return refuse(" ".join(form.errors['username']) if 'username' in form.errors else "Pseudo invalide.", 400)

    if form.cleaned_data['username'] != form.initial['username']:
        form.save()
        USERNAME_CHANGES.record(key)
    if wants_json:
        return JsonResponse({'success': True, 'username': request.user.username})
    messages.success(request, "Pseudo mis à jour.")
    return redirect('account')

@login_required(login_url='login')
def settings_home_view(request):
    """Page des réglages : toutes les rubriques (informations, notifications, aide) et la déconnexion."""
    return render(request, 'account_settings_home.html', {'feedback_threads_count': request.user.feedbacks.count()})
