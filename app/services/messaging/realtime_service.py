import json
import logging
from datetime import timedelta

import requests
import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings
from django.db.models import prefetch_related_objects
from django.utils import timezone
from django.utils.html import strip_tags

from app.services.messaging import notification_presenter as presenter
from app.services.messaging.security import get_secure_channel_name

logger = logging.getLogger(__name__)

PUSH_BODY_MAX_LENGTH = 180

_firebase_attempted = False

NOTIFICATION_RELATIONS = ('recipient', 'sender', 'beer', 'brewery', 'bar', 'spot', 'report', 'feedback', 'feedback__messages', 'sender__socialaccount_set')
FCM_BATCH_SIZE = 500  # limite de messages par appel de Firebase
DAILY_ALERTS_PER_MEMBER = 3  # pop-ups et push par membre et par jour ; toutes les notifications restent dans sa liste


def _firebase_ready():
    try:
        firebase_admin.get_app()
        return True
    except ValueError:
        return False


def init_firebase():
    """Active le push Android si FIREBASE_CREDENTIALS_JSON est défini ; le dit clairement dans les journaux sinon."""
    if _firebase_ready():
        return True
    raw_json = settings.FIREBASE_CREDENTIALS_JSON
    if not raw_json:
        if not settings.DEBUG:
            logger.warning("Push Android désactivé : FIREBASE_CREDENTIALS_JSON n'est pas défini.")
        return False
    try:
        firebase_admin.initialize_app(credentials.Certificate(json.loads(raw_json)))
        return True
    except Exception as e:  # JSON invalide ou identifiants refusés : jamais bloquant pour le site
        logger.error("Impossible d'initialiser Firebase : %s", type(e).__name__)  # jamais le contenu : c'est un secret
        return False


def _push_enabled():
    """Firebase est initialisé au premier envoi, pas à l'import du module : une page qui n'envoie rien ne paie pas ce démarrage."""
    global _firebase_attempted
    if not _firebase_attempted:
        _firebase_attempted = True
        init_firebase()
    return _firebase_ready()


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


def _push_text(message_html):
    # Fallback de sécurité au cas où le template renvoie du vide
    return strip_tags(message_html).strip()[:PUSH_BODY_MAX_LENGTH] or "Vous avez une nouvelle notification."


def _send_pushes(candidates):
    """Envoi natif Android via Firebase, par lots (un appel réseau pour 500 notifications, pas un par notification).

    `candidates` : [(notification, texte HTML, adresse de lecture)]. Renvoie les notifications que l'appareil a reçues. Une erreur
    n'interrompt jamais le reste."""
    delivered = []
    for start in range(0, len(candidates), FCM_BATCH_SIZE):
        chunk = candidates[start:start + FCM_BATCH_SIZE]
        try:
            batch = messaging.send_each([_build_push(notif, _push_text(html), read_url) for notif, html, read_url in chunk])
        except Exception as e:
            logger.warning("Erreur d'envoi FCM (%s notifications) : %s", len(chunk), e)
            continue
        for (notif, _html, _url), response in zip(chunk, batch.responses):
            if response.success:
                delivered.append(notif)
            elif isinstance(response.exception, (messaging.UnregisteredError, messaging.SenderIdMismatchError)):
                # Application désinstallée ou jeton périmé : inutile de continuer à l'utiliser
                type(notif.recipient).objects.filter(pk=notif.recipient_id, fcm_token=notif.recipient.fcm_token).update(fcm_token=None)
            else:
                logger.warning("Erreur d'envoi FCM pour le membre %s : %s", notif.recipient_id, response.exception)
    return delivered


def _within_daily_alerts(notifications):
    """Sépare les notifications en (à signaler, à garder seulement dans la liste).

    Un membre n'est signalé (push, pop-up temps réel) que pour ses `DAILY_ALERTS_PER_MEMBER` premières notifications des dernières 24 h ;
    les suivantes sont enregistrées, non lues, comptées par la pastille et visibles dans sa liste, mais ne le dérangent pas."""
    from ...models import Notification

    recipients = {notif.recipient_id for notif in notifications}
    rank = {}
    seen = {}
    for pk, recipient_id in (Notification.objects.filter(recipient_id__in=recipients, created_at__gte=timezone.now() - timedelta(days=1))
                             .order_by('id').values_list('pk', 'recipient_id')):
        rank[pk] = seen.get(recipient_id, 0)
        seen[recipient_id] = rank[pk] + 1
    alerted = [notif for notif in notifications if rank.get(notif.pk, 0) < DAILY_ALERTS_PER_MEMBER]
    silent = [notif for notif in notifications if rank.get(notif.pk, 0) >= DAILY_ALERTS_PER_MEMBER]
    return alerted, silent


def mark_toasted(notifications):
    """Mémorise qu'une alerte a déjà été montrée : elle ne sera plus proposée en pop-up à l'ouverture d'une page."""
    ids = [notif.pk for notif in notifications]
    if ids:
        type(notifications[0]).objects.filter(pk__in=ids, toasted_at__isnull=True).update(toasted_at=timezone.now())


def broadcast_notifications(notifications_list):
    """Envoie une liste de notifications via le WebSocket Supabase en 1 seule requête, et en push Android via Firebase (par lots)."""
    notifications_list = [notif for notif in (notifications_list or []) if notif.id]  # ignore les notifications bloquées par les préférences
    if not notifications_list:
        return
    # Le plafond quotidien vaut même si aucun canal n'est configuré : une notification au-delà ne doit jamais ressortir en pop-up plus tard
    notifications_list, silent = _within_daily_alerts(notifications_list)
    mark_toasted(silent)  # elle reste non lue dans la liste, mais n'affiche ni push ni pop-up
    supabase_enabled = bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)
    push_enabled = _push_enabled()
    if not notifications_list or not (supabase_enabled or push_enabled):
        return

    # Destinataires, expéditeurs et cibles chargés en une fois par type : le texte de chaque notification n'interroge plus la base
    prefetch_related_objects(notifications_list, *NOTIFICATION_RELATIONS)

    messages = []
    achievements_cache = {}
    to_push = []

    for notif in notifications_list:
        achievement = None
        if notif.notif_type == presenter.ACHIEVEMENT and supabase_enabled:
            achievement = presenter.achievements_by_slug(notif.recipient, achievements_cache).get(notif.achievement_slug)
        data = presenter.payload(notif, achievement)

        if push_enabled and getattr(notif.recipient, 'fcm_token', None):
            to_push.append((notif, data['message'], data['read_url']))

        if supabase_enabled:
            messages.append({
                "topic": get_secure_channel_name(notif.recipient),
                "event": "new_notification",
                "payload": {key: data[key] for key in ('slug', 'message', 'read_url', 'toastType', 'tier_slug', 'icon')},
            })

    # l'appareil l'a affichée : pas de pop-up en double à la prochaine ouverture
    mark_toasted(_send_pushes(to_push))
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
