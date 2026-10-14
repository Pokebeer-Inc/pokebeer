"""Compte du membre connecté : profil et réglages, pseudo, suppression du compte."""
from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
import logging

from ..forms import (
    AccountDeletionForm, FeedbackForm, MarketingConsentForm, NotificationPreferenceForm, ProSettingsForm, UserUpdateForm, UsernameForm, error_summary,
)
from ..models import AccountDeletion, Drinks
from ..services.establishments import team
from ..services.members import account, password_reset
from ..services.members.achievements import get_user_achievements
from ..services.support.feedback import FeedbackError, open_thread
from ..services.members.follows import follow_context
from ..services.members.inactivity import delete_account
from ..services.members.profile_stats import get_top_beers_data, get_user_statistics
from ..services.protection.throttle import USERNAME_ATTEMPTS, USERNAME_CHANGES
from .utils import picker_context

logger = logging.getLogger(__name__)

TOO_MANY_USERNAME_CHANGES = "Trop de changements de pseudo. Réessayez plus tard."

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
    previous_email = user.email  # lue avant la validation : le formulaire recopie les valeurs saisies dans l'instance
    form = forms['profile_form'] = UserUpdateForm(request.POST, instance=user)
    if form.is_valid():
        account.update_profile(form, previous_email)
        messages.success(request, "Profil mis à jour.")
        return done()
    messages.error(request, "Profil non modifié : " + " ; ".join(error_summary(form)))


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
        'team_invitations': team.invitations_for(user),
        'feedback_threads_count': user.feedbacks.count(),
        # Choix des fenêtres du Top 3 : premières dégustations, la suite par recherche et « Charger plus »
        'top_picker': picker_context(user, 'top'),
        **follow_context(user),
        'top_beers_data': _with_other_slots(get_top_beers_data(user, my_drinks, include_empty=True)),
        'unlocked_achievements': [a for a in all_achievements if a['tier_level'] > 0],
        'level': level_data['current_level'],
        **get_user_statistics(my_drinks),
    }


def _with_other_slots(top_beers):
    """Chaque emplacement du Top 3 connaît les bières des deux autres (on ne peut pas les y choisir une seconde fois)."""
    for item in top_beers:
        item['other_beer_slugs'] = ','.join(other['beer'].slug for other in top_beers if other is not item and other['beer'])
        item['picker_uid'] = f"top-{item['slot']}"
    return top_beers


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


def delete_account_view(request):
    """Supprime le compte de l'utilisateur et ses données associées (sauf les bières du catalogue), après confirmation de son identité
    (mot de passe actuel, ou pseudo pour un compte sans mot de passe)."""
    if request.method != 'POST':
        return redirect('account')
    form = AccountDeletionForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, "Compte non supprimé : " + " ; ".join(error_summary(form)))
        return redirect('account_settings_home')
    user = request.user
    # La session est fermée d'abord, puis le compte supprimé (CASCADE et SET_NULL gérés par Django), avec une trace sans donnée personnelle
    logout(request)
    delete_account(user, AccountDeletion.Reason.SELF)
    messages.success(request, "Votre compte et toutes vos données personnelles ont été supprimés. Au revoir !")
    return redirect('index')

@require_POST
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

    if USERNAME_CHANGES.exceeded(key) or not USERNAME_ATTEMPTS.hit(key):
        return refuse(TOO_MANY_USERNAME_CHANGES, 429)

    form = UsernameForm(request.POST, instance=request.user)
    if not form.is_valid():
        return refuse(" ".join(form.errors['username']) if 'username' in form.errors else "Pseudo invalide.", 400)

    if form.cleaned_data['username'] != form.initial['username']:
        if not USERNAME_CHANGES.hit(key):  # compté de façon atomique : deux envois simultanés ne dépassent pas le plafond
            return refuse(TOO_MANY_USERNAME_CHANGES, 429)
        form.save()
    if wants_json:
        return JsonResponse({'success': True, 'username': request.user.username})
    messages.success(request, "Pseudo mis à jour.")
    return redirect('account')

def settings_home_view(request):
    """Page des réglages : toutes les rubriques (informations, notifications, aide) et la déconnexion."""
    return render(request, 'account_settings_home.html', {
        'feedback_threads_count': request.user.feedbacks.count(),
        'deletion_form': AccountDeletionForm(user=request.user),
    })
