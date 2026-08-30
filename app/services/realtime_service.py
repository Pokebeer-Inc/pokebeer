import requests
import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse
from app.services.security import get_secure_channel_name
from django.utils.html import strip_tags

# Initialisation de Firebase
if not firebase_admin._apps and getattr(settings, 'FIREBASE_CREDENTIALS_PATH', None):
    try:
        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"Attention: Impossible d'initialiser Firebase ({e})")
        
def broadcast_notifications(notifications_list):
    """Envoie une liste de notifications via le WebSocket Supabase en 1 seule requête."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY or not notifications_list:
        return

    # Import local pour éviter les imports circulaires
    from app.views.utils import get_user_achievements 
    
    messages = []
    user_achievements = None

    for notif in notifications_list:
        if not notif.id:
            continue # Sécurité : Ignore les notifications bloquées par les préférences utilisateur
        
        toast_type = 'info'
        tier_slug = None
        icon_html = None
        
        if notif.notif_type == 'report_updated': 
            toast_type = 'warning'
        elif notif.notif_type in ['beer_added', 'spot_invite', 'feedback_replied']: 
            toast_type = 'success'
        elif notif.notif_type == 'achievement':
            if user_achievements is None:
                user_achievements, _ = {ach['name']: ach for ach in get_user_achievements(notif.recipient)}
                
            if notif.achievement_name in user_achievements:
                ach_data = user_achievements[notif.achievement_name]
                tier_slug = ach_data['tier_slug']
                icon_html = render_to_string('partials/achievement_icon.html', {'slug': ach_data['slug']}).strip()

        message_html = render_to_string('partials/notification_text.html', {'notif': notif}).strip()
        
        payload = {
            "id": notif.id,
            "message": message_html,
            "read_url": reverse('read_notification', args=[notif.id]),
            "toastType": toast_type,
            "tier_slug": tier_slug,
            "icon": icon_html
        }
        
        messages.append({
            "topic": get_secure_channel_name(notif.recipient_id),
            "event": "new_notification",
            "payload": payload
        })
        
        # Envoi natif Android via Firebase
        if getattr(notif.recipient, 'fcm_token', None) and firebase_admin._apps:
            try:
                clean_text = strip_tags(message_html).strip() 
                
                # Fallback de sécurité au cas où le template renvoie du vide
                if not clean_text:
                    clean_text = "Vous avez une nouvelle notification."
                
                push_message = messaging.Message(
                    notification=messaging.Notification(
                        title="Pokebeer",
                        body=clean_text,
                    ),
                    token=notif.recipient.fcm_token,
                )
                messaging.send(push_message)
            except Exception as e:
                print(f"Erreur d'envoi FCM pour {notif.recipient.username}: {e}", flush=True)

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