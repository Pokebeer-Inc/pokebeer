"""Avatar par défaut : initiale du pseudo sur fond ambre, généré localement (aucun service externe)."""
from html import escape
from urllib.parse import quote

BACKGROUND = '#E5A022'


def initials_avatar_url(username):
    """Data URI SVG ; le pseudo est échappé, jamais inséré tel quel dans le SVG."""
    initial = escape((str(username or '?').strip() or '?')[0].upper())
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" fill="{BACKGROUND}"/>'
        '<text x="50%" y="50%" dy=".35em" text-anchor="middle" fill="#fff" font-weight="bold" '
        f'font-family="Arial, Helvetica, sans-serif" font-size="30">{initial}</text></svg>'
    )
    return 'data:image/svg+xml,' + quote(svg)
