from datetime import timedelta

from django.db.models import F, Sum
from django.utils import timezone

from ..models import ChatUsage

CHAT = 'chat'
LABEL_SCAN = 'label'
EAN_LOOKUP = 'ean'


WEEK = timedelta(days=7)


def _used_this_week(user, scope):
    """Appels des 7 derniers jours (aujourd'hui compris) : une fenêtre glissante, sans jour de remise à zéro à guetter."""
    since = timezone.localdate() - WEEK + timedelta(days=1)
    return ChatUsage.objects.filter(user=user, scope=scope, day__gte=since).aggregate(total=Sum('count'))['total'] or 0


def consume_quota(user, daily_limit, scope=CHAT, weekly_limit=None):
    """Réserve un appel du quota de l'utilisateur pour cet usage (par jour et, si donné, sur 7 jours glissants). Renvoie False si épuisé."""
    usage, _ = ChatUsage.objects.get_or_create(user=user, day=timezone.localdate(), scope=scope)
    # Incrément conditionnel en une seule requête : deux appels simultanés ne peuvent pas dépasser la limite
    if ChatUsage.objects.filter(pk=usage.pk, count__lt=daily_limit).update(count=F('count') + 1) != 1:
        return False
    # Réservation d'abord, vérification ensuite : deux appels simultanés ne peuvent pas passer ensemble sous le plafond hebdomadaire
    if weekly_limit is not None and _used_this_week(user, scope) > weekly_limit:
        refund_quota(user, scope)
        return False
    return True


def refund_quota(user, scope=CHAT):
    """Rend l'appel réservé par `consume_quota` quand le service n'a pas pu répondre : le membre ne perd pas sa question."""
    ChatUsage.objects.filter(user=user, day=timezone.localdate(), scope=scope, count__gt=0).update(count=F('count') - 1)
