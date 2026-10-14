"""Pages qui suivent l'inscription (formulaire classique ou Google) : date de naissance (obligatoire, majorité), genre (facultatif), puis
choix des e-mails promotionnels (case cochée par défaut).

Chaque page enregistre sa réponse en base dès qu'elle est validée ; tant que la dernière n'est pas passée, le middleware
(app/middleware.py) renvoie le membre ici. Rien de ce qui est saisi n'est affiché aux autres membres.
"""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import Resolver404, resolve
from django.utils.http import url_has_allowed_host_and_scheme

from ..forms import BirthDateForm, GenderForm, MarketingConsentForm
from ..services.messaging import marketing
from ..services.protection.throttle import ONBOARDING_ATTEMPTS

__all__ = ['onboarding_start_view', 'onboarding_birth_view', 'onboarding_gender_view', 'onboarding_emails_view', 'ONBOARDING_NEXT_KEY']

ONBOARDING_NEXT_KEY = 'onboarding_next'
TOTAL_STEPS = 3


def _next_page(request):
    """Page demandée avant l'interruption par les pages d'inscription (si elle est sur ce site), sinon l'accueil."""
    target = request.session.pop(ONBOARDING_NEXT_KEY, None)
    if target and target.startswith('/') and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        try:
            resolve(target.split('?', 1)[0])  # une adresse qui ne mène à aucune page de l'application ne doit pas finir en erreur 404
        except Resolver404:
            return 'index'
        return target
    return 'index'


def onboarding_start_view(request):
    """Reprend là où le membre s'était arrêté."""
    user = request.user
    if user.onboarding_done:
        return redirect(_next_page(request))
    if not user.birth_date:
        return redirect('onboarding_birth')
    return redirect('onboarding_emails' if user.gender else 'onboarding_gender')


def onboarding_birth_view(request):
    """Étape 1 : date de naissance, obligatoire et d'une personne majeure."""
    user = request.user
    if user.onboarding_done:
        return redirect('index')

    key = f"user:{user.pk}"
    if request.method == 'POST':
        if not ONBOARDING_ATTEMPTS.hit(key):
            messages.error(request, "Trop d'essais. Réessayez dans quelques minutes.")
            form = BirthDateForm(instance=user)
        else:
            form = BirthDateForm(request.POST, instance=user)
            if form.is_valid():
                user.birth_date = form.cleaned_data['birth_date']
                user.save(update_fields=['birth_date'])
                return redirect('onboarding_gender')
    else:
        form = BirthDateForm(instance=user)
    return render(request, 'onboarding_birth.html', {'form': form, 'step': 1, 'total': TOTAL_STEPS, 'hide_nav': True})


def onboarding_gender_view(request):
    """Étape 2 : genre, facultatif. « Suivant » enregistre le choix, « Passer » (ou aucun choix) n'enregistre rien."""
    user = request.user
    if user.onboarding_done:
        return redirect('index')
    if not user.birth_date:
        return redirect('onboarding_birth')  # la date de naissance est obligatoire : on ne peut pas arriver ici sans elle

    if request.method == 'POST':
        form = GenderForm(request.POST, instance=user)
        if 'skip' not in request.POST and not form.is_valid():
            messages.error(request, "Choisissez l'une des réponses proposées, ou passez cette étape.")
        else:
            user.gender = '' if 'skip' in request.POST else form.cleaned_data.get('gender', '')
            user.save(update_fields=['gender'])
            return redirect('onboarding_emails')
    else:
        form = GenderForm(instance=user)
    return render(request, 'onboarding_gender.html', {'form': form, 'step': 2, 'total': TOTAL_STEPS, 'hide_nav': True})


def onboarding_emails_view(request):
    """Étape 3 (dernière) : recevoir ou non les nouveautés par e-mail. La case est cochée par défaut ; le choix est horodaté et modifiable
    à tout moment dans les réglages."""
    user = request.user
    if user.onboarding_done:
        return redirect('index')
    if not user.birth_date:
        return redirect('onboarding_birth')

    # Une case décochée n'est pas envoyée : un POST vide reste une réponse (refus), d'où le test sur la méthode et non sur les données
    form = MarketingConsentForm(request.POST if request.method == 'POST' else None, user=user, source=marketing.ONBOARDING)
    if request.method == 'POST' and form.is_valid():
        form.save()
        user.onboarding_done = True
        user.save(update_fields=['onboarding_done'])
        messages.success(request, f"Bienvenue, {user.username} ! Votre compte est prêt.")
        return redirect(_next_page(request))
    return render(request, 'onboarding_emails.html', {'form': form, 'step': 3, 'total': TOTAL_STEPS, 'hide_nav': True})
