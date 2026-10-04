"""Réinitialisation du mot de passe par e-mail.

- Le lien contient un jeton signé (HMAC) lié à l'ancien mot de passe : il ne sert qu'une fois, expire (PASSWORD_RESET_TIMEOUT)
  et devient invalide dès que le membre se connecte ou change son mot de passe.
- La demande ne dit jamais si l'adresse a un compte. Un compte sans mot de passe (connexion Google) ne reçoit jamais de
  lien : il reçoit un message lui rappelant de se connecter avec Google, ce qui interdit d'ajouter une porte dérobée à
  un compte géré par Google.
- Les comptes suspendus ne reçoivent rien.
"""
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.formats import date_format
from django.utils.http import urlsafe_base64_encode

from ..models import BeerUser
from . import mailer
from .throttle import PASSWORD_RESET_BY_EMAIL, PASSWORD_RESET_GLOBAL

GLOBAL_KEY = 'all'


def reset_url(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    path = reverse('password_reset_confirm', args=[uid, default_token_generator.make_token(user)])
    return f'{settings.PUBLIC_BASE_URL}{path}'


def can_reset(user):
    """Seul un compte actif qui possède un mot de passe peut en réinitialiser un."""
    return user.is_active and user.has_usable_password()


def request_password_reset(email):
    """Envoie les instructions adaptées à chaque compte portant cette adresse ; ne renvoie rien, volontairement.

    La demande est comptée qu'un compte existe ou non (pas d'oracle), et au-delà des plafonds elle est ignorée sans le dire.
    """
    email = email.strip().lower()
    if PASSWORD_RESET_BY_EMAIL.exceeded(email) or PASSWORD_RESET_GLOBAL.exceeded(GLOBAL_KEY):
        return
    PASSWORD_RESET_BY_EMAIL.record(email)
    PASSWORD_RESET_GLOBAL.record(GLOBAL_KEY)

    for user in BeerUser.objects.filter(email__iexact=email, is_active=True):
        if user.has_usable_password():
            context = {'user': user, 'reset_url': reset_url(user), 'validity_minutes': settings.PASSWORD_RESET_TIMEOUT // 60}
            mailer.send_templated(user.email, "Réinitialisation de votre mot de passe Pokebeer", 'password_reset', context)
        else:
            mailer.send_templated(user.email, "Connexion à Pokebeer avec Google", 'password_reset_google', {'user': user})


def notify_password_changed(user):
    """Prévient le membre (à son adresse enregistrée) qu'un mot de passe vient d'être défini."""
    when = date_format(timezone.localtime(), 'j F Y à H:i')
    mailer.send_templated(user.email, "Votre mot de passe Pokebeer a été modifié", 'password_changed', {'user': user, 'when': when})
