from django.conf import settings
from app.services.security import get_secure_channel_name

def supabase_config(request):
    """Expose les clés publiques Supabase à tous les templates HTML."""
    context = {
        'SUPABASE_URL': settings.SUPABASE_URL,
        'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
    }
    
    # Si l'utilisateur est connecté, on lui donne sa clé de canal privée
    if request.user.is_authenticated:
        context['WS_CHANNEL_NAME'] = get_secure_channel_name(request.user.id)
    return context