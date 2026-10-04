import hmac

from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_GET

from ..services.inactivity import purge_inactive_accounts

__all__ = ['purge_inactive_accounts_cron']


@require_GET
def purge_inactive_accounts_cron(request):
    """Tâche quotidienne (Vercel Cron) : prévient puis supprime les comptes inactifs."""
    secret = settings.CRON_SECRET
    # Sans secret configuré l'endpoint reste fermé : jamais de suppression déclenchable anonymement
    if not secret or not hmac.compare_digest(request.headers.get('Authorization', ''), f'Bearer {secret}'):
        return HttpResponseForbidden()
    warned, deleted = purge_inactive_accounts()
    return JsonResponse({'warned': warned, 'deleted': deleted})
