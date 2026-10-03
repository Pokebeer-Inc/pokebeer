import logging

import requests
import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.html import strip_tags

from app.services import notification_presenter as presenter
from app.services.security import get_secure_channel_name

logger = logging.getLogger(__name__)

PUSH_BODY_MAX_LENGTH = 180

# Initialisation de Firebase
if not firebase_admin._apps and getattr(settings, 'FIREBASE_CREDENTIALS_PATH', None):
    try:
        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        logger.warning("Impossible d'initialiser Firebase (%s)", e)


def _build_push(notif, text, read_url):
    return messaging.Message(
        notification=messaging.Notification(title="Pokebeer", body=text),
        # Chemin relatif : l'application Android l'ouvre sur son propre domaine (jamais un hôte fourni par le message)
        data={"read_url": read_url, "notif_slug": notif.slug},
        android=messaging.AndroidConfig(
            priority='high',
            collapse_key=notif.slug,
            notification=messaging.AndroidNotification(channel_id=settings.FCM_ANDROID_CHANNEL_ID, tag=notif.slug),
        ),
        token=notif.recipient.fcm_token,
    )


def _send_push(notif, message_html, read_url):
    """Envoi natif Android via Firebase ; renvoie True si l'appareil a reçu l'alerte. Une erreur n'interrompt jamais le reste."""
    # Fallback de sécurité au cas où le template renvoie du vide
    text = strip_tags(message_html).strip()[:PUSH_BODY_MAX_LENGTH] or "Vous avez une nouvelle notification."
    try:
        messaging.send(_build_push(notif, text, read_url))
        return True
    except (messaging.UnregisteredError, messaging.SenderIdMismatchError):
        # Application désinstallée ou jeton périmé : inutile de continuer à l'utiliser
        notif.recipient.__class__.objects.filter(pk=notif.recipient_id, fcm_token=notif.recipient.fcm_token).update(fcm_token=None)
    except Exception as e:
        logger.warning("Erreur d'envoi FCM pour le membre %s : %s", notif.recipient_id, e)
    return False


def mark_toasted(notifications):
    """Mémorise qu'une alerte a déjà été montrée : elle ne sera plus proposée en pop-up à l'ouverture d'une page."""
    ids = [notif.pk for notif in notifications]
    if ids:
        type(notifications[0]).objects.filter(pk__in=ids, toasted_at__isnull=True).update(toasted_at=timezone.now())


def broadcast_notifications(notifications_list):
    """Envoie une liste de notifications via le WebSocket Supabase en 1 seule requête, et en push Android via Firebase."""
    supabase_enabled = bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)
    push_enabled = bool(firebase_admin._apps)
    if not notifications_list or not (supabase_enabled or push_enabled):
        return

    messages = []
    achievements_cache = {}
    pushed = []

    for notif in notifications_list:
        if not notif.id:
            continue  # Sécurité : ignore les notifications bloquées par les préférences utilisateur

        achievement = None
        if notif.notif_type == presenter.ACHIEVEMENT and supabase_enabled:
            achievement = presenter.achievements_by_name(notif.recipient, achievements_cache).get(notif.achievement_name)
        data = presenter.payload(notif, achievement)

        if push_enabled and getattr(notif.recipient, 'fcm_token', None):
            if _send_push(notif, data['message'], data['read_url']):
                pushed.append(notif)  # l'appareil l'a affichée : pas de pop-up en double à la prochaine ouverture

        if supabase_enabled:
            messages.append({
                "topic": get_secure_channel_name(notif.recipient_id),
                "event": "new_notification",
                "payload": {key: data[key] for key in ('slug', 'message', 'read_url', 'toastType', 'tier_slug', 'icon')},
            })

    mark_toasted(pushed)
    if not supabase_enabled:
        return

    url = f"{settings.SUPABASE_URL}/realtime/v1/api/broadcast"
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json"
    }

    try:
        # timeout=(0.5, 1) -> 0.5s pour se connecter, 1s max pour lire.
        # Si Supabase rame, on abandonne silencieusement pour ne pas bloquer l'utilisateur.
        response = requests.post(url, json={"messages": messages}, headers=headers, timeout=(0.5, 1))
        if response.status_code >= 400:
            logger.warning("Supabase Broadcast refusé (%s) : %s", response.status_code, response.text)
    except Exception as e:
        logger.warning("Erreur réseau Supabase Broadcast : %s", e)
