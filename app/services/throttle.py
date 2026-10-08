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

# E-mails de la suppression des comptes inactifs : plafond quotidien, pour laisser du quota Gmail aux mots de passe oubliés
INACTIVITY_EMAIL_GLOBAL = Rule('inactivity-email', 100, timedelta(days=1))

# Annonce d'une nouvelle politique : deux publications par jour au plus (garde-fou contre un double clic) et un quota d'e-mails
# quotidien qui laisse de la place aux mots de passe oubliés et aux avertissements d'inactivité (Gmail : 500 par jour)
POLICY_NOTICE_PUBLISH = Rule('policy-notice', 2, timedelta(days=1))
POLICY_EMAIL_GLOBAL = Rule('policy-email', 80, timedelta(days=1))

# Bienvenue : e-mail envoyé à l'inscription, au-delà du plafond il est simplement omis (le compte est créé quoi qu'il arrive)
WELCOME_EMAIL_GLOBAL = Rule('welcome-email', 100, timedelta(days=1))

# Campagnes de l'administration : quota d'e-mails par jour (réglable, voir settings) et garde-fou contre les lancements répétés
CAMPAIGN_EMAIL_GLOBAL = Rule('campaign-email', settings.CAMPAIGN_EMAIL_DAILY_LIMIT, timedelta(days=1))
CAMPAIGN_LAUNCH = Rule('campaign-launch', 5, timedelta(days=1))

# Vérification des doublons pendant la saisie d'une bière (une requête après chaque pause de frappe)
CATALOG_CHECK_BY_USER = Rule('catalog-check', 600, timedelta(hours=1))

# Recherche des communes d'un code postal (formulaires d'établissement, y compris à l'inscription : sans connexion, donc par adresse IP)
POSTAL_LOOKUP_BY_IP = Rule('postal-ip', 120, timedelta(hours=1))

# Demandes de gestion d'un établissement : quelques-unes par jour et par membre (chacune est examinée à la main par l'équipe)
CLAIM_BY_USER = Rule('claim-user', 5, timedelta(days=1))

# Page publique de choix des e-mails (lien signé reçu par e-mail)
EMAIL_PREFERENCES_BY_IP = Rule('email-prefs-ip', 30, timedelta(hours=1))

# Assistant Gaétan : rafale par membre (en plus du quota quotidien) et budget d'appels au modèle pour toute l'application, afin de
# rester dans le quota gratuit de Gemini
CHAT_BURST_BY_USER = Rule('chat-burst', 5, timedelta(minutes=1))
CHAT_GLOBAL = Rule('chat-global', settings.CHAT_GLOBAL_DAILY_LIMIT, timedelta(days=1))
CHAT_GLOBAL_KEY = 'all'
