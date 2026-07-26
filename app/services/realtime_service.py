import requests
from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse
from app.services.security import get_secure_channel_name

def broadcast_notifications(notifications_list):
    """Envoie une liste de notifications via le WebSocket Supabase en 1 seule requête."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY or not notifications_list:
        return

    # Import local pour éviter les imports circulaires
    from app.views.utils import get_user_achievements 
    
    messages = []
    user_achievements = None

    for notif in notifications_list:
        toast_type = 'info'
        tier_slug = None
        icon_html = None
        
        if notif.notif_type == 'report_updated': 
            toast_type = 'warning'
        elif notif.notif_type in ['beer_added', 'spot_invite']: 
            toast_type = 'success'
        elif notif.notif_type == 'achievement':
            if user_achievements is None:
                user_achievements = {ach['name']: ach for ach in get_user_achievements(notif.recipient)}
                
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