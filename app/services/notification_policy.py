"""Qui a le droit de recevoir quoi : appliqué à toute notification créée, quel que soit l'appelant."""
from . import notification_types


def filter_allowed(notifications):
    """Ne garde que les notifications autorisées, en un nombre constant de requêtes."""
    # Imports locaux : ce module est appelé depuis models.py
    from django.db.models import Q
    from ..models import BeerUser, UserBlock

    notifications = list(notifications)
    for notif in notifications:
        notification_types.get(notif.notif_type)  # rejette les types inconnus

    recipient_ids = {n.recipient_id for n in notifications}
    recipients = BeerUser.objects.in_bulk(recipient_ids)

    # Paires (destinataire, expéditeur) bloquées dans un sens ou dans l'autre
    sender_ids = {n.sender_id for n in notifications if n.sender_id}
    blocked_pairs = set()
    if sender_ids:
        blocks = UserBlock.objects.filter(
            Q(blocker_id__in=recipient_ids, blocked_id__in=sender_ids)
            | Q(blocker_id__in=sender_ids, blocked_id__in=recipient_ids)
        ).values_list('blocker_id', 'blocked_id')
        for blocker, blocked in blocks:
            blocked_pairs.update([(blocker, blocked), (blocked, blocker)])

    return [
        notif for notif in notifications
        if _is_allowed(notif, recipients.get(notif.recipient_id), blocked_pairs)
    ]


def _is_allowed(notif, recipient, blocked_pairs):
    if recipient is None or not recipient.is_active:
        return False
    if notif.sender_id:
        if notif.sender_id == notif.recipient_id or (notif.recipient_id, notif.sender_id) in blocked_pairs:
            return False

    notif_type = notification_types.get(notif.notif_type)
    if notif_type.is_system:
        return True
    return recipient.notif_global and getattr(recipient, notif_type.category)
