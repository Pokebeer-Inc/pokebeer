"""Choix des e-mails promotionnels et liens signés pour le gérer sans se connecter.

Les e-mails promotionnels sont reçus par défaut ; chaque choix du membre (désinscription ou retour) est horodaté avec son origine. Les liens des e-mails contiennent un jeton
signé (SECRET_KEY) qui ne désigne que le compte : il ne donne accès à rien d'autre que ce choix, et peut être refusé en un clic
(en-têtes List-Unsubscribe, exigés par Gmail et Yahoo pour les envois en nombre).
"""
from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone

from ..models import BeerUser

SALT = 'marketing-preferences'
ACCOUNT, EMAIL_LINK = 'account', 'email_link'


def _token(user):
    return signing.dumps(user.pk, salt=SALT, compress=False)


def user_for_token(token):
    """Compte désigné par un jeton, ou None (jeton falsifié, compte supprimé ou suspendu). Le jeton n'expire pas : un lien de
    désinscription doit fonctionner dans un vieil e-mail."""
    try:
        pk = signing.loads(token, salt=SALT)
    except signing.BadSignature:
        return None
    return BeerUser.objects.filter(pk=pk, is_active=True).first()


def preferences_url(user):
    return f"{settings.PUBLIC_BASE_URL}{reverse('email_preferences', args=[_token(user)])}"


def unsubscribe_url(user):
    return f"{settings.PUBLIC_BASE_URL}{reverse('email_unsubscribe', args=[_token(user)])}"


def unsubscribe_headers(user):
    """En-têtes RFC 8058 : le client de messagerie propose « Se désabonner » et le fait par un simple POST."""
    return {
        'List-Unsubscribe': f'<{unsubscribe_url(user)}>, <mailto:{settings.SUPPORT_EMAIL}?subject=Desabonnement>',
        'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
    }


def set_consent(user, opted_in, source):
    """Enregistre le choix du membre ; renvoie False (sans rien écrire) s'il ne change rien, pour garder la preuve d'origine."""
    if user.marketing_consent_at and user.marketing_opt_in == opted_in:
        return False
    now = timezone.now()
    BeerUser.objects.filter(pk=user.pk).update(marketing_opt_in=opted_in, marketing_consent_at=now, marketing_consent_source=source)
    user.marketing_opt_in, user.marketing_consent_at, user.marketing_consent_source = opted_in, now, source
    return True
