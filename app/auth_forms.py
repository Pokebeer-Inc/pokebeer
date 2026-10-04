"""Formulaires de connexion protégés contre le brute-force (site public et administration)."""
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError

from .services.throttle import LOGIN_BY_ACCOUNT, LOGIN_BY_IP, client_ip


class ThrottledLoginMixin:
    """Bloque les tentatives au-delà des limites par adresse IP et par compte, sans même tester le mot de passe.

    Un message unique, qu'il s'agisse de l'IP ou du compte : rien ne révèle quelle limite est atteinte.
    """

    throttled_message = "Trop de tentatives de connexion. Réessayez dans quelques minutes."

    def clean(self):
        ip = client_ip(self.request)
        account = self.cleaned_data.get('username') or ''
        if LOGIN_BY_IP.exceeded(ip) or (account and LOGIN_BY_ACCOUNT.exceeded(account)):
            raise ValidationError(self.throttled_message, code='throttled')
        try:
            cleaned = super().clean()
        except ValidationError:
            LOGIN_BY_IP.record(ip)
            if account:
                LOGIN_BY_ACCOUNT.record(account)
            raise
        if account:
            LOGIN_BY_ACCOUNT.reset(account)  # une connexion réussie ne laisse pas de compteur à un tiers
        return cleaned


class ThrottledAdminAuthenticationForm(ThrottledLoginMixin, AdminAuthenticationForm):
    pass
