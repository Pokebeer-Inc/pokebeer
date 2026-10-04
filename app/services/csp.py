"""Politique de sécurité du contenu (CSP) : seules les origines utilisées par le site sont autorisées.

Les gabarits contiennent des scripts et gestionnaires `onclick` en ligne : `'unsafe-inline'` reste donc nécessaire pour
les scripts. La politique bloque néanmoins tout script, objet ou formulaire venu d'une origine inconnue, le
détournement de `<base>` et l'affichage du site dans la page d'un tiers.
"""
from urllib.parse import urlparse

SELF = "'self'"
CDN_SCRIPTS = ('https://cdn.jsdelivr.net', 'https://unpkg.com')
GOOGLE_FONTS = 'https://fonts.googleapis.com'
FONT_FILES = 'https://fonts.gstatic.com'
GEOCODERS = ('https://nominatim.openstreetmap.org', 'https://ipapi.co')


def _realtime_origins(supabase_url):
    """Origines HTTPS et WebSocket du projet Supabase (diffusion temps réel des notifications)."""
    host = urlparse(supabase_url or '').netloc
    return (f'https://{host}', f'wss://{host}') if host else ()


def build_policy(supabase_url=None, admin=False):
    """En-tête Content-Security-Policy. L'administration (Alpine.js d'Unfold) exige en plus `'unsafe-eval'`."""
    script_src = [SELF, "'unsafe-inline'", *CDN_SCRIPTS] + (["'unsafe-eval'"] if admin else [])
    directives = {
        'default-src': [SELF],
        'script-src': script_src,
        'style-src': [SELF, "'unsafe-inline'", 'https://unpkg.com', GOOGLE_FONTS],
        'font-src': [SELF, FONT_FILES, 'data:'],
        'img-src': [SELF, 'data:', 'blob:', 'https:'],  # photos hébergées (S3, avatars Google), tuiles de carte
        'connect-src': [SELF, *_realtime_origins(supabase_url), *GEOCODERS],
        'object-src': ["'none'"],
        'base-uri': [SELF],
        'form-action': [SELF],
        'frame-ancestors': [SELF],
    }
    return '; '.join(f"{name} {' '.join(sources)}" for name, sources in directives.items())
