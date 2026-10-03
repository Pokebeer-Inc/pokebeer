"""Point d'entrée unique pour envoyer des notifications."""
from ..models import Notification
from .realtime_service import broadcast_notifications


def create_notifications(notif_type, recipients, sender=None, **refs):
    """Crée une notification par destinataire (utilisateurs ou ids) ; la politique d'envoi écarte les refusées.

    `refs` : objets liés (beer=, brewery=, bar=, spot=, report=, feedback=) ou `text_content=`.
    """
    notifications = [
        Notification(
            recipient_id=getattr(recipient, 'pk', recipient), sender=sender, notif_type=notif_type, **refs,
        )
        for recipient in recipients
    ]
    return Notification.objects.bulk_create(notifications)


def notify(notif_type, recipients, sender=None, **refs):
    """Crée puis diffuse (WebSocket + push) ; renvoie les notifications réellement créées."""
    return send_notifications(create_notifications(notif_type, recipients, sender, **refs))


def send_notifications(created):
    """Diffuse (WebSocket + push) des notifications déjà créées et les renvoie."""
    broadcast_notifications(created)
    return created
