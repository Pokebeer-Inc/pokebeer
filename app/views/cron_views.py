import hmac

from django.core.management import call_command

from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_GET

from ..services.messaging.campaigns import send_pending as send_pending_campaigns
from ..services.members.inactivity import purge_inactive_accounts
from ..services.messaging.policy_notice import send_pending_emails

__all__ = ['purge_inactive_accounts_cron']


@require_GET
def purge_inactive_accounts_cron(request):
    """Tâche quotidienne (Vercel Cron) : comptes inactifs (avertissement, suppression) suite des e-mails d'annonce de politique et des campagnes e-mail."""
    secret = settings.CRON_SECRET
    # Sans secret configuré l'endpoint reste fermé : jamais de suppression déclenchable anonymement
    if not secret or not hmac.compare_digest(request.headers.get('Authorization', '').encode(), f'Bearer {secret}'.encode()):
        return HttpResponseForbidden()  # comparé en octets : un en-tête non ASCII ne fait pas planter la comparaison
    call_command('clearsessions')  # RGPD : les sessions expirées ne restent pas en base
    warned, deleted = purge_inactive_accounts()
    return JsonResponse({'warned': warned, 'deleted': deleted, 'policy_emails': send_pending_emails(), 'campaign_emails': send_pending_campaigns()})
