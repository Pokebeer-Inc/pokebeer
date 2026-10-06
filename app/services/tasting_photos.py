"""Photos de dégustation : validation stricte puis ré-encodage, stockées dans media/tastings/ (Supabase en production).

Le fichier envoyé n'est jamais conservé tel quel (voir images.reencode_as_webp) ; le nom est aléatoire et l'URL non devinable.
"""
from .images import random_webp_path, reencode_as_webp, shrink_to_fit

UPLOAD_DIR = 'tastings'
MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # Vercel refuse de toute façon les requêtes de plus de 4,5 Mo
MAX_SIDE = 1280
DAILY_LIMIT = 30
QUOTA_SCOPE = 'tasting_photo'


def tasting_photo_path(instance, filename):
    return random_webp_path(UPLOAD_DIR)


def process_tasting_photo(upload):
    """Valide l'envoi et renvoie une image WebP bornée à MAX_SIDE pixels, prête à être stockée (ValidationError sinon)."""
    return reencode_as_webp(upload, MAX_UPLOAD_BYTES, lambda image: shrink_to_fit(image, MAX_SIDE), name='tasting.webp', quality=82)
