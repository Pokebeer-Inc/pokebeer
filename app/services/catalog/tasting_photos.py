"""Photos de dégustation : validation stricte puis ré-encodage, stockées dans media/tastings/ (Supabase en production).

Le fichier envoyé n'est jamais conservé tel quel (voir images.reencode_as_webp) ; le nom est aléatoire et l'URL non devinable.
"""
from ..common.images import PHOTO_MAX_SIDE as MAX_SIDE, PHOTO_MAX_UPLOAD_BYTES as MAX_UPLOAD_BYTES, process_photo  # noqa: F401  (réexportés)

DAILY_LIMIT = 30
QUOTA_SCOPE = 'tasting_photo'


def process_tasting_photo(upload):
    """Valide l'envoi et renvoie une image WebP bornée à MAX_SIDE pixels, prête à être stockée (ValidationError sinon)."""
    return process_photo(upload, 'tasting.webp')
