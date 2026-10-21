"""Limitation de débit des actions sensibles (connexion, inscription), partagée entre toutes les instances.

Les tentatives sont stockées en base : sur Vercel chaque fonction a sa propre mémoire, un compteur en cache local
serait contourné. Les clés (IP, pseudo) sont hachées avec la SECRET_KEY : la table ne contient aucune donnée personnelle.
"""
import hashlib
import hmac
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from ...models import ThrottleHit

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


def _lock(scope, key_hash):
    """Verrou PostgreSQL propre à (règle, clé), libéré à la fin de la transaction : deux requêtes simultanées sur la même clé
    passent l'une après l'autre, les autres clés ne sont jamais bloquées."""
    lock_id = int(hashlib.sha256(f'{scope}:{key_hash}'.encode()).hexdigest()[:15], 16)  # 60 bits : tient dans un bigint signé
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock_id])


@dataclass(frozen=True)
class Rule:
    """Au plus `attempts` tentatives par clé sur la fenêtre glissante `window`."""
    scope: str
    attempts: int
    window: timedelta

    def _in_window(self, key_hash):
        return ThrottleHit.objects.filter(scope=self.scope, key_hash=key_hash, created_at__gte=timezone.now() - self.window)

    def _hits(self, key):
        return self._in_window(_digest(key))

    def exceeded(self, key):
        """Lecture seule : la limite est-elle atteinte ? Pour consommer une tentative, utiliser `hit`."""
        return self._hits(key).count() >= self.attempts

    def record(self, key):
        """Compte une tentative sans condition (ex. un échec constaté après coup)."""
        ThrottleHit.objects.filter(created_at__lt=timezone.now() - RETENTION).delete()
        ThrottleHit.objects.create(scope=self.scope, key_hash=_digest(key))

    def hit(self, key):
        """Vérifie ET compte une tentative en une seule opération : True si elle est admise, False si la limite est atteinte (rien
        n'est alors compté). Des requêtes simultanées sur la même clé ne peuvent pas passer ensemble sous le plafond."""
        key_hash = _digest(key)
        with transaction.atomic():
            _lock(self.scope, key_hash)
            if self._in_window(key_hash).count() >= self.attempts:
                return False
            self.record(key)
        return True

    def release(self, key):
        """Rend la dernière tentative comptée par `hit` (l'action n'a finalement pas eu lieu, ou a réussi et ne doit pas compter)."""
        latest = self._hits(key).order_by('-created_at', '-pk').values('pk')[:1]
        ThrottleHit.objects.filter(pk__in=latest).delete()

    def reset(self, key):
        self._hits(key).delete()


LOGIN_BY_IP = Rule('login-ip', 10, timedelta(minutes=15))
LOGIN_BY_ACCOUNT = Rule('login-account', 20, timedelta(minutes=15))
SIGNUP_BY_IP = Rule('signup-ip', 10, timedelta(hours=1))
PRO_SIGNUP_BY_IP = Rule('pro-signup-ip', 5, timedelta(hours=1))

# Changement de pseudo, par membre : essais plafonnés (on ne sonde pas les pseudos libres) et changements réellement effectués
USERNAME_ATTEMPTS = Rule('username-attempts', 10, timedelta(hours=1))
USERNAME_CHANGES = Rule('username-changes', 3, timedelta(days=1))

# Pages qui suivent l'inscription : essais de date de naissance par membre
ONBOARDING_ATTEMPTS = Rule('onboarding-birth', 20, timedelta(hours=1))

# Enregistrements du brouillon d'ajout de bière (une validation par étape, plus l'enregistrement en quittant la page)
BEER_DRAFT_SAVES = Rule('beer-draft', 200, timedelta(hours=1))

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

# Autocomplétions (bières, brasseries, membres à inviter dans une équipe) : une requête après chaque pause de frappe
AUTOCOMPLETE_BY_USER = Rule('autocomplete', 600, timedelta(hours=1))

# Analytics d'un établissement (page des gérants, exports compris) : chaque affichage lance des agrégats sur toute la période
PRO_ANALYTICS_BY_USER = Rule('pro-analytics', 120, timedelta(hours=1))

# Confirmation d'identité (mot de passe ou pseudo) avant une action sensible : changement d'e-mail, suppression du compte
IDENTITY_CONFIRM_BY_USER = Rule('identity-confirm', 5, timedelta(minutes=15))

# Invitations à rejoindre l'équipe d'un établissement, par gérant
TEAM_INVITE_BY_USER = Rule('team-invite', 20, timedelta(days=1))

# Recherche des communes d'un code postal (formulaires d'établissement, y compris à l'inscription : sans connexion, donc par adresse IP)
POSTAL_LOOKUP_BY_IP = Rule('postal-ip', 120, timedelta(hours=1))

# Demandes de gestion d'un établissement : quelques-unes par jour et par membre (chacune est examinée à la main par l'équipe)
CLAIM_BY_USER = Rule('claim-user', 5, timedelta(days=1))

# Page publique de choix des e-mails (lien signé reçu par e-mail)
EMAIL_PREFERENCES_BY_IP = Rule('email-prefs-ip', 30, timedelta(hours=1))

# Assistant Gaétan : rafale par membre (en plus du quota quotidien) et budget d'appels au modèle pour toute l'application, afin de
# rester dans les limites du plan gratuit de Mistral
# Suggestions de modification d'une fiche : quelques-unes par jour et par membre (chacune est relue par l'équipe)
SUGGESTION_BY_USER = Rule('suggestion-user', 10, timedelta(days=1))

CHAT_BURST_BY_USER = Rule('chat-burst', 5, timedelta(minutes=1))
CHAT_GLOBAL = Rule('chat-global', settings.CHAT_GLOBAL_DAILY_LIMIT, timedelta(days=1))
CHAT_MODEL_CALLS = Rule('chat-model-calls', settings.CHAT_MODEL_CALLS_PER_MINUTE, timedelta(minutes=1))
CHAT_GLOBAL_KEY = 'all'
