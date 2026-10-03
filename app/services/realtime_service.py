import requests
import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse
from app.services import notification_types
from app.services.security import get_secure_channel_name
from django.utils.html import strip_tags

# Initialisation de Firebase
if not firebase_admin._apps and getattr(settings, 'FIREBASE_CREDENTIALS_PATH', None):
    try:
        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"Attention: Impossible d'initialiser Firebase ({e})")
        
def _achievements_by_name(recipient, cache):
    """Trophées d'un destinataire indexés par nom, calculés une seule fois par destinataire."""
    # Import local pour éviter les imports circulaires
    from app.services.achievements import get_user_achievements

    if recipient.pk not in cache:
        achievements, _level = get_user_achievements(recipient)
        cache[recipient.pk] = {ach['name']: ach for ach in achievements}
    return cache[recipient.pk]

def _send_push(notif, message_html, read_url):
    """Envoi natif Android via Firebase ; une erreur n'interrompt jamais le reste de la diffusion."""
    try:
        # Fallback de sécurité au cas où le template renvoie du vide
        clean_text = strip_tags(message_html).strip() or "Vous avez une nouvelle notification."
        push_message = messaging.Message(
            notification=messaging.Notification(
                title="Pokebeer",
                body=clean_text,
            ),
            # Chemin relatif : l'application Android l'ouvre sur son propre domaine (jamais un hôte fourni par le message)
            data={"read_url": read_url},
            token=notif.recipient.fcm_token,
        )
        messaging.send(push_message)
    except Exception as e:
        print(f"Erreur d'envoi FCM pour {notif.recipient.username}: {e}")

def broadcast_notifications(notifications_list):
    """Envoie une liste de notifications via le WebSocket Supabase en 1 seule requête, et en push Android via Firebase."""
    supabase_enabled = bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)
    push_enabled = bool(firebase_admin._apps)
    if not notifications_list or not (supabase_enabled or push_enabled):
        return

    messages = []
    achievements_cache = {}

    for notif in notifications_list:
        if not notif.id:
            continue # Sécurité : Ignore les notifications bloquées par les préférences utilisateur

        message_html = render_to_string('partials/notification_text.html', {'notif': notif}).strip()
        read_url = reverse('read_notification', args=[notif.slug])

        if push_enabled and getattr(notif.recipient, 'fcm_token', None):
            _send_push(notif, message_html, read_url)

        if not supabase_enabled:
            continue
        
        toast_type = notification_types.get(notif.notif_type).toast
        tier_slug = None
        icon_html = None
        
        if notif.notif_type == 'achievement':
            ach_data = _achievements_by_name(notif.recipient, achievements_cache).get(notif.achievement_name)
            if ach_data:
                tier_slug = ach_data['tier_slug']
                icon_html = render_to_string('partials/achievement_icon.html', {'slug': ach_data['slug']}).strip()
        
        payload = {
            "slug": notif.slug,
            "message": message_html,
            "read_url": read_url,
            "toastType": toast_type,
            "tier_slug": tier_slug,
            "icon": icon_html
        }
        
        messages.append({
            "topic": get_secure_channel_name(notif.recipient_id),
            "event": "new_notification",
            "payload": payload
        })

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
            print(f"ERREUR SUPABASE ({response.status_code}): {response.text}")
        else:
            print(f"Supabase Broadcast envoyé avec succès pour {len(messages)} notif(s)")
            
    except Exception as e:
        print(f"Erreur réseau Supabase Broadcast : {e}")