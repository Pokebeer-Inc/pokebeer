"""Annonce d'une modification de la politique de confidentialité.

Chaque membre actif reçoit une notification (liste et pop-up à sa prochaine visite) qui ouvre la politique. L'e-mail est
facultatif : il atteint aussi ceux qui ne reviennent plus, mais le compte Gmail n'en permet que quelques dizaines par jour ;
il part donc par lots, à chaque exécution de la tâche quotidienne, jusqu'à ce que tous les membres l'aient reçu.
"""
from django.conf import settings

from ..models import BeerUser, PolicyNotice
from . import mailer
from .notifications import create_notifications
from .throttle import POLICY_EMAIL_GLOBAL, POLICY_NOTICE_PUBLISH

NOTIFICATION = 'policy_updated'
EMAIL_SUBJECT = "Mise à jour de la politique de confidentialité de Pokebeer"
CHUNK = 500
GLOBAL_KEY = 'all'


class TooManyNotices(Exception):
    """Une annonce vient déjà d'être publiée : pas de seconde avant un moment."""


def audience():
    return BeerUser.objects.filter(is_active=True)


def publish(summary, by_email, author):
    """Crée l'annonce et notifie tous les membres actifs ; l'e-mail éventuel suit par lots (send_pending_emails)."""
    if POLICY_NOTICE_PUBLISH.exceeded(GLOBAL_KEY):
        raise TooManyNotices
    POLICY_NOTICE_PUBLISH.record(GLOBAL_KEY)

    notified = 0
    ids = list(audience().values_list('pk', flat=True))
    for start in range(0, len(ids), CHUNK):
        notified += len(create_notifications(NOTIFICATION, ids[start:start + CHUNK], text_content=summary))
    return PolicyNotice.objects.create(
        summary=summary, created_by=author, notified_count=notified, notify_by_email=by_email, email_done=not by_email,
    )


def send_pending_emails():
    """Envoie la suite des e-mails des annonces en cours, dans la limite du quota du jour ; renvoie le nombre envoyé."""
    sent = 0
    for notice in PolicyNotice.objects.filter(notify_by_email=True, email_done=False).order_by('created_at'):
        sent += _send_batch(notice)
        if POLICY_EMAIL_GLOBAL.exceeded(GLOBAL_KEY):
            break
    return sent


def _send_batch(notice):
    sent = 0
    for member in audience().filter(pk__gt=notice.email_cursor).order_by('pk').iterator():
        if POLICY_EMAIL_GLOBAL.exceeded(GLOBAL_KEY):
            break
        POLICY_EMAIL_GLOBAL.record(GLOBAL_KEY)
        if mailer.send_templated(member.email, EMAIL_SUBJECT, 'policy_updated', {
            'user': member, 'summary': notice.summary, 'policy_url': settings.PRIVACY_POLICY_URL,
        }):
            sent += 1
        # Le curseur avance même après un échec : un seul membre en panne ne bloque pas les suivants
        notice.email_cursor = member.pk
        notice.save(update_fields=['email_cursor'])
    else:
        notice.email_done = True  # tous les membres ont été traités
    notice.emails_sent += sent
    notice.save(update_fields=['emails_sent', 'email_done'])
    return sent
