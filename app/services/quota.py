from django.db.models import F
from django.utils import timezone

from ..models import ChatUsage

CHAT = 'chat'
LABEL_SCAN = 'label'
EAN_LOOKUP = 'ean'


def consume_quota(user, daily_limit, scope=CHAT):
    """Réserve un appel du quota quotidien de l'utilisateur pour cet usage. Renvoie False si le quota est épuisé."""
    usage, _ = ChatUsage.objects.get_or_create(user=user, day=timezone.localdate(), scope=scope)
    # Incrément conditionnel en une seule requête : deux appels simultanés ne peuvent pas dépasser la limite
    return ChatUsage.objects.filter(pk=usage.pk, count__lt=daily_limit).update(count=F('count') + 1) == 1
