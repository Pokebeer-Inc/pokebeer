from django.conf import settings

def supabase_config(request):
    """Expose les clés publiques Supabase à tous les templates HTML."""
    return {
        'SUPABASE_URL': settings.SUPABASE_URL,
        'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
    }