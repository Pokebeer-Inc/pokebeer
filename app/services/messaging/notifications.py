"""Point d'entrée unique pour créer et envoyer des notifications : la politique d'envoi (type connu, destinataire actif, préférences,
blocages : voir notification_policy) s'applique ici à toute notification, quel que soit l'appelant."""
from ...models import Notification
from .notification_policy import filter_allowed
from .realtime_service import broadcast_notifications


def save_notifications(notifications):
    """Enregistre les notifications admises par la politique d'envoi (en une requête) et les renvoie ; les autres sont écartées."""
    allowed = filter_allowed(notifications)
    return Notification.objects.bulk_create(allowed) if allowed else []


def create_notifications(notif_type, recipients, sender=None, **refs):
    """Crée une notification par destinataire (utilisateurs ou ids) ; la politique d'envoi écarte les refusées.

    `refs` : objets liés (beer=, brewery=, bar=, spot=, report=, feedback=) ou `text_content=`.
    """
    return save_notifications(
        Notification(recipient_id=getattr(recipient, 'pk', recipient), sender=sender, notif_type=notif_type, **refs)
        for recipient in recipients
    )


def notify(notif_type, recipients, sender=None, **refs):
    """Crée puis diffuse (WebSocket + push) ; renvoie les notifications réellement créées."""
    return send_notifications(create_notifications(notif_type, recipients, sender, **refs))


def send_notifications(created):
    """Diffuse (WebSocket + push) des notifications déjà créées et les renvoie."""
    broadcast_notifications(created)
    return created
