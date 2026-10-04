"""Limitation de débit des actions sensibles (connexion, inscription), partagée entre toutes les instances.

Les tentatives sont stockées en base : sur Vercel chaque fonction a sa propre mémoire, un compteur en cache local
serait contourné. Les clés (IP, pseudo) sont hachées avec la SECRET_KEY : la table ne contient aucune donnée personnelle.
"""
import hashlib
import hmac
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from ..models import ThrottleHit

RETENTION = timedelta(days=1)  # plus longue que toute fenêtre ci-dessous


def client_ip(request):
    """Adresse du visiteur. Seul le dernier proxy de confiance est cru : le reste de X-Forwarded-For est falsifiable."""
    forwarded = [part.strip() for part in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if part.strip()]
    proxies = settings.TRUSTED_PROXY_COUNT
    if proxies and len(forwarded) >= proxies:
        return forwarded[-proxies]
    return request.META.get('REMOTE_ADDR') or 'unknown'


def _digest(key):
    return hmac.new(settings.SECRET_KEY.encode(), str(key).lower().encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Rule:
    """Au plus `attempts` tentatives par clé sur la fenêtre glissante `window`."""
    scope: str
    attempts: int
    window: timedelta

    def _hits(self, key):
        return ThrottleHit.objects.filter(scope=self.scope, key_hash=_digest(key), created_at__gte=timezone.now() - self.window)

    def exceeded(self, key):
        return self._hits(key).count() >= self.attempts

    def record(self, key):
        ThrottleHit.objects.filter(created_at__lt=timezone.now() - RETENTION).delete()
        ThrottleHit.objects.create(scope=self.scope, key_hash=_digest(key))

    def reset(self, key):
        self._hits(key).delete()


LOGIN_BY_IP = Rule('login-ip', 10, timedelta(minutes=15))
LOGIN_BY_ACCOUNT = Rule('login-account', 20, timedelta(minutes=15))
SIGNUP_BY_IP = Rule('signup-ip', 10, timedelta(hours=1))
PRO_SIGNUP_BY_IP = Rule('pro-signup-ip', 5, timedelta(hours=1))

# Réinitialisation du mot de passe : par IP (refus explicite), par adresse et au total (silencieux, pour ne rien révéler).
# Le plafond quotidien protège le quota d'envoi du compte Gmail (500 messages par jour).
PASSWORD_RESET_BY_IP = Rule('reset-ip', 5, timedelta(hours=1))
PASSWORD_RESET_BY_EMAIL = Rule('reset-email', 3, timedelta(hours=1))
PASSWORD_RESET_GLOBAL = Rule('reset-global', 300, timedelta(days=1))
PASSWORD_RESET_CONFIRM_BY_IP = Rule('reset-confirm-ip', 10, timedelta(hours=1))
