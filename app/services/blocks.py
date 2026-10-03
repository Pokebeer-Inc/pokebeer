"""Blocages entre membres : invitation à signaler quand un même membre est bloqué par plusieurs personnes."""
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from ..models import UserBlock
from .notifications import notify

# Un membre bloqué par autant de personnes distinctes mérite un examen (et une invitation à signaler)
REPEATED_BLOCK_THRESHOLD = 3


def repeatedly_blocked_count():
    """Nombre de membres bloqués par au moins REPEATED_BLOCK_THRESHOLD personnes distinctes."""
    return (
        UserBlock.objects.values('blocked').annotate(n=Count('blocker', distinct=True))
        .filter(n__gte=REPEATED_BLOCK_THRESHOLD).count()
    )


def invite_blockers_to_report(blocked):
    """Quand `blocked` atteint le seuil, invite chaque bloqueur pas encore invité à signaler un éventuel problème.

    Le message ne mentionne ni le nombre de blocages ni les autres bloqueurs, et le membre bloqué n'est jamais prévenu.
    """
    with transaction.atomic():
        blocks = UserBlock.objects.select_for_update().filter(blocked=blocked)
        if blocks.values('blocker').distinct().count() < REPEATED_BLOCK_THRESHOLD:
            return []
        pending = list(blocks.filter(report_invited_at__isnull=True))
        if not pending:
            return []
        UserBlock.objects.filter(pk__in=[b.pk for b in pending]).update(report_invited_at=timezone.now())
    return notify('block_follow_up', [b.blocker_id for b in pending], text_content=blocked.username)
