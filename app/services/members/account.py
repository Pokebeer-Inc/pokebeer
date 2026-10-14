"""Profil du membre connecté : enregistrement et ce qui en découle (avis de sécurité, trophées)."""
from . import identity
from .achievements import check_and_notify_achievements


def update_profile(profile_form, previous_email):
    """Enregistre l'adresse e-mail et la biographie (formulaire validé). Un changement d'adresse est signalé à l'ancienne ; la biographie
    compte pour un trophée caché."""
    user = profile_form.save()
    if profile_form.email_changed:
        identity.notify_email_changed(user, previous_email)
    check_and_notify_achievements(user)
    return user
