"""Envoi des e-mails transactionnels : un gabarit texte et un gabarit HTML par message (templates/emails/)."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def send_templated(to, subject, template, context, headers=None):
    """Envoie `emails/<template>.txt` + `.html` à `to` ; renvoie False (sans lever) si l'envoi échoue.

    Une panne du serveur d'e-mail ne doit jamais faire planter la page ni, par la différence de réponse, révéler quoi que ce soit.
    `headers` : en-têtes supplémentaires (ex. List-Unsubscribe des e-mails promotionnels).
    """
    context = {**context, 'support_email': settings.SUPPORT_EMAIL, 'base_url': settings.PUBLIC_BASE_URL}
    message = EmailMultiAlternatives(
        subject, render_to_string(f'emails/{template}.txt', context), settings.DEFAULT_FROM_EMAIL, [to],
        reply_to=[settings.SUPPORT_EMAIL], headers=headers,
    )
    message.attach_alternative(render_to_string(f'emails/{template}.html', context), 'text/html')
    try:
        message.send()
    except Exception:  # SMTP refusé, délai dépassé, identifiants invalides…
        logger.exception("Envoi de l'e-mail « %s » impossible", template)
        return False
    return True
