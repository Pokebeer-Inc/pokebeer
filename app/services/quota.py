from django.db.models import F
from django.utils import timezone

from ..models import ChatUsage


def consume_chat_quota(user, daily_limit):
    """Réserve un message du quota quotidien de l'utilisateur. Renvoie False si le quota est épuisé."""
    usage, _ = ChatUsage.objects.get_or_create(user=user, day=timezone.localdate())
    # Incrément conditionnel en une seule requête : deux appels simultanés ne peuvent pas dépasser la limite
    return ChatUsage.objects.filter(pk=usage.pk, count__lt=daily_limit).update(count=F('count') + 1) == 1
