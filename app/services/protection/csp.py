"""Politique de sécurité du contenu (CSP) : seules les origines utilisées par le site sont autorisées.

Le site public n'exécute aucun JavaScript en ligne : les rares scripts de gabarit portent un `nonce` aléatoire propre à chaque réponse
(`request.csp_nonce`) et les actions des boutons sont déclarées par des attributs `data-*` (static/script/ui_actions.js). Un script injecté
dans une page ne peut donc pas s'exécuter. L'administration (gabarits d'Unfold, qu'on ne contrôle pas) garde `'unsafe-inline'` et
`'unsafe-eval'`. La politique bloque aussi tout objet ou formulaire venu d'une origine inconnue, le détournement de `<base>` et
l'affichage du site dans la page d'un tiers.
"""
from urllib.parse import urlparse

SELF = "'self'"
CDN_SCRIPTS = ('https://cdn.jsdelivr.net',)
GOOGLE_FONTS = 'https://fonts.googleapis.com'
FONT_FILES = 'https://fonts.gstatic.com'
GEOCODERS = ('https://nominatim.openstreetmap.org',)
# Le bouton « Continuer avec Google » envoie un formulaire (POST) que le serveur redirige vers Google : `form-action` s'applique
# aussi à cette redirection, sans quoi le navigateur la bloque et la page reste figée.
OAUTH_FORM_TARGETS = ('https://accounts.google.com',)


def _realtime_origins(supabase_url):
    """Origines HTTPS et WebSocket du projet Supabase (diffusion temps réel des notifications)."""
    host = urlparse(supabase_url or '').netloc
    return (f'https://{host}', f'wss://{host}') if host else ()


def build_policy(supabase_url=None, admin=False, nonce=None):
    """En-tête Content-Security-Policy. `nonce` : jeton de la réponse, seul moyen d'exécuter un script en ligne sur le site public.
    L'administration (Alpine.js d'Unfold) exige `'unsafe-inline'` et `'unsafe-eval'`."""
    if admin or not nonce:
        script_src = [SELF, "'unsafe-inline'", *CDN_SCRIPTS] + (["'unsafe-eval'"] if admin else [])
    else:
        script_src = [SELF, f"'nonce-{nonce}'", *CDN_SCRIPTS]
    directives = {
        'default-src': [SELF],
        'script-src': script_src,
        'style-src': [SELF, "'unsafe-inline'", GOOGLE_FONTS],
        'font-src': [SELF, FONT_FILES, 'data:'],
        'img-src': [SELF, 'data:', 'blob:', 'https:'],  # photos hébergées (S3, avatars Google), tuiles de carte
        'connect-src': [SELF, *_realtime_origins(supabase_url), *GEOCODERS],
        'object-src': ["'none'"],
        'base-uri': [SELF],
        'form-action': [SELF, *OAUTH_FORM_TARGETS],
        'frame-ancestors': [SELF],
    }
    return '; '.join(f"{name} {' '.join(sources)}" for name, sources in directives.items())
