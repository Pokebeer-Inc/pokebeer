"""E-mails liés à la suppression des comptes inactifs (adresse d'envoi : celle du service, comme la réinitialisation du mot de passe).

Un plafond quotidien partagé réserve une part du quota du compte Gmail (500 messages par jour) aux réinitialisations de mot
de passe : l'envoi s'arrête une fois le plafond atteint et reprend à la prochaine exécution, sans jamais perdre un membre.
"""
from django.conf import settings

from . import mailer
from .throttle import INACTIVITY_EMAIL_GLOBAL

GLOBAL_KEY = 'all'
WARNING_SUBJECT = "Votre compte Pokebeer sera supprimé pour inactivité"
DELETION_SUBJECT = "Votre compte Pokebeer a été supprimé"


def capacity_left():
    return not INACTIVITY_EMAIL_GLOBAL.exceeded(GLOBAL_KEY)


def _send(to, subject, template, context):
    INACTIVITY_EMAIL_GLOBAL.record(GLOBAL_KEY)
    return mailer.send_templated(to, subject, template, {
        **context, 'months': settings.INACTIVE_ACCOUNT_MONTHS, 'warning_days': settings.INACTIVE_ACCOUNT_WARNING_DAYS,
    })


def send_warning(user, deadline):
    """Préavis : date de suppression (déjà mise en forme) et moyen de l'éviter. Renvoie True si l'e-mail est parti."""
    return _send(user.email, WARNING_SUBJECT, 'inactivity_warning', {'user': user, 'deadline': deadline})


def send_deletion_notice(email, username):
    """Confirmation envoyée une fois le compte supprimé ; l'adresse n'est plus conservée ensuite. Sans effet au-delà du plafond."""
    if not capacity_left():
        return False
    return _send(email, DELETION_SUBJECT, 'account_deleted', {'username': username})
