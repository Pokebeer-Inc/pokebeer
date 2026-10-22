import hmac
from functools import wraps

from django.core.management import call_command

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_GET

from ..services.catalog.context_reminders import send_pending as send_context_reminders
from ..services.catalog.draw_reminders import send_pending as send_draw_reminders
from ..services.messaging.campaigns import send_pending as send_pending_campaigns
from ..services.tracking.retention import purge_expired as purge_tracking
from ..services.members.inactivity import purge_inactive_accounts
from ..services.messaging.policy_notice import send_pending_emails

__all__ = ['purge_inactive_accounts_cron', 'daily_draw_reminder_cron']


def cron_job(view):
    """Tâche planifiée (Vercel Cron) : appel GET authentifié par le secret de la tâche (Authorization: Bearer), jamais par une session."""
    @login_not_required
    @require_GET
    @wraps(view)
    def guarded(request):
        secret = settings.CRON_SECRET
        # Sans secret configuré l'endpoint reste fermé : jamais d'action déclenchable anonymement
        if not secret or not hmac.compare_digest(request.headers.get('Authorization', '').encode(), f'Bearer {secret}'.encode()):
            return HttpResponseForbidden()  # comparé en octets : un en-tête non ASCII ne fait pas planter la comparaison
        return view(request)
    return guarded


@cron_job
def purge_inactive_accounts_cron(request):
    """Tâche quotidienne : comptes inactifs (avertissement, suppression) suite des e-mails d'annonce de politique, des campagnes e-mail, des rappels de contexte et de la purge des mesures d'usage."""
    call_command('clearsessions')  # RGPD : les sessions expirées ne restent pas en base
    warned, deleted = purge_inactive_accounts()
    return JsonResponse({
        'warned': warned, 'deleted': deleted, 'policy_emails': send_pending_emails(), 'campaign_emails': send_pending_campaigns(),
        'context_reminders': send_context_reminders(), 'tracking_purged': purge_tracking(),
    })


@cron_job
def daily_draw_reminder_cron(request):
    """Rappel push du tirage du jour, à 18 h heure de Paris (la tâche est appelée à 16 h et 17 h UTC : le service n'envoie qu'à la bonne heure)."""
    return JsonResponse({'draw_reminders': send_draw_reminders()})
