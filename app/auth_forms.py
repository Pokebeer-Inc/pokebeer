"""Formulaires de connexion protégés contre le brute-force (site public et administration)."""
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError

from .services.protection.throttle import LOGIN_BY_ACCOUNT, LOGIN_BY_IP, client_ip


class ThrottledLoginMixin:
    """Bloque les tentatives au-delà des limites par adresse IP et par compte, sans même tester le mot de passe.

    Un message unique, qu'il s'agisse de l'IP ou du compte : rien ne révèle quelle limite est atteinte.
    """

    throttled_message = "Trop de tentatives de connexion. Réessayez dans quelques minutes."

    def clean(self):
        # Chaque tentative est comptée AVANT le test du mot de passe (de façon atomique) : des essais lancés en parallèle ne peuvent pas
        # passer ensemble sous le plafond. Seuls les échecs restent comptés.
        ip = client_ip(self.request)
        account = self.cleaned_data.get('username') or ''
        if not LOGIN_BY_IP.hit(ip):
            raise ValidationError(self.throttled_message, code='throttled')
        if account and not LOGIN_BY_ACCOUNT.hit(account):
            LOGIN_BY_IP.release(ip)
            raise ValidationError(self.throttled_message, code='throttled')
        cleaned = super().clean()
        LOGIN_BY_IP.release(ip)
        if account:
            LOGIN_BY_ACCOUNT.reset(account)  # une connexion réussie ne laisse pas de compteur à un tiers
        return cleaned


class ThrottledAdminAuthenticationForm(ThrottledLoginMixin, AdminAuthenticationForm):
    pass
