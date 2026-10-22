"""Photos des souvenirs de la carte : même contrôle que les photos de dégustation, stockées dans le dossier spots/ du bucket des médias.

Le fichier envoyé n'est jamais conservé tel quel (voir images.reencode_as_webp) ; le nom est aléatoire et l'URL non devinable.
"""
from ..common.images import process_photo

DAILY_LIMIT = 30
QUOTA_SCOPE = 'spot_photo'


def process_spot_photo(upload):
    """Valide l'envoi et renvoie une image WebP bornée, prête à être stockée (ValidationError sinon)."""
    return process_photo(upload, 'spot.webp')
