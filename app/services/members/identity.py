"""Confirmation d'identité avant une action sensible (changement d'adresse e-mail, suppression du compte), et avis de sécurité.

Un compte avec mot de passe confirme avec son mot de passe actuel ; un compte sans mot de passe (connexion Google) retape son pseudo.
Les essais sont limités par membre : seuls les échecs restent comptés, une session volée ne permet pas de deviner le mot de passe.
"""
from django.utils import timezone
from django.utils.formats import date_format

from ..messaging import mailer
from ..protection.throttle import IDENTITY_CONFIRM_BY_USER

TOO_MANY_ATTEMPTS = "Trop d'essais. Réessayez dans quelques minutes."


class IdentityNotConfirmed(Exception):
    """Confirmation refusée : le message est affichable tel quel."""


def uses_password(user):
    """Vrai si le membre confirme avec son mot de passe ; faux pour un compte sans mot de passe (connexion Google)."""
    return user.has_usable_password()


def confirm(user, secret):
    """Vérifie le mot de passe actuel (ou le pseudo, pour un compte sans mot de passe) ; lève IdentityNotConfirmed sinon."""
    if not IDENTITY_CONFIRM_BY_USER.hit(user.pk):
        raise IdentityNotConfirmed(TOO_MANY_ATTEMPTS)
    secret = secret or ''
    if uses_password(user):
        if not user.check_password(secret):
            raise IdentityNotConfirmed("Mot de passe incorrect.")
    elif secret.strip().lower() != user.username.lower():
        raise IdentityNotConfirmed("Le pseudo saisi ne correspond pas au vôtre.")
    IDENTITY_CONFIRM_BY_USER.release(user.pk)  # seuls les échecs restent comptés


def notify_email_changed(user, previous_email):
    """Prévient l'ANCIENNE adresse qu'elle n'est plus celle du compte : si ce n'est pas le membre, il peut réagir."""
    when = date_format(timezone.localtime(), 'j F Y à H:i')
    return mailer.send_templated(previous_email, "L'adresse e-mail de votre compte Pokebeer a été modifiée", 'email_changed', {
        'user': user, 'when': when, 'new_email': user.email,
    })
