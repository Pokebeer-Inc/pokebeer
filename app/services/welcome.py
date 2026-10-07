"""E-mail de bienvenue envoyé à la création d'un compte (formulaire, établissement pro ou connexion Google).

C'est un message de service : il présente l'application, et prévient que les nouveautés arriveront par e-mail avec le moyen
de s'en désinscrire.
"""
from django.db import transaction
from django.utils import timezone

from ..models import BeerUser
from . import app_links, mailer, marketing
from .throttle import WELCOME_EMAIL_GLOBAL

SUBJECT = "Bienvenue sur Pokebeer 🍺"
GLOBAL_KEY = 'all'


def send_welcome(user):
    """Envoie la bienvenue une seule fois par compte ; renvoie True si l'e-mail est parti.

    Le compte est « réservé » avant l'envoi (mise à jour conditionnelle) : deux déclenchements simultanés n'envoient qu'un message.
    Au-delà du plafond quotidien, ou en cas de panne, rien n'est envoyé et l'inscription n'en est jamais affectée.
    """
    if WELCOME_EMAIL_GLOBAL.exceeded(GLOBAL_KEY):
        return False
    claimed = BeerUser.objects.filter(pk=user.pk, welcome_sent_at__isnull=True).update(welcome_sent_at=timezone.now())
    if not claimed:
        return False
    WELCOME_EMAIL_GLOBAL.record(GLOBAL_KEY)
    sent = mailer.send_templated(user.email, SUBJECT, 'welcome', {
        'user': user, 'highlights': app_links.highlights(), 'preferences_url': marketing.preferences_url(user),
    })
    if not sent:
        BeerUser.objects.filter(pk=user.pk).update(welcome_sent_at=None)
    return sent


def send_welcome_after_commit(user):
    """Pour les créations de compte faites dans une transaction : l'e-mail ne part que si le compte existe vraiment."""
    transaction.on_commit(lambda: send_welcome(user))


def connect_signals():
    """Les inscriptions Google passent par allauth, qui signale la création du compte."""
    from allauth.account.signals import user_signed_up
    user_signed_up.connect(lambda sender, request, user, **kwargs: send_welcome_after_commit(user), weak=False, dispatch_uid='welcome-email')
