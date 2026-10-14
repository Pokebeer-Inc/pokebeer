"""Images officielles (bières, brasseries, bars) : mêmes garanties que les photos de dégustation (voir images.reencode_as_webp)."""
from ..common.images import reencode_as_webp, shrink_to_fit

MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # Vercel refuse de toute façon les requêtes de plus de 4,5 Mo
MAX_SIDE = 1600


def process_official_image(upload):
    """Valide l'envoi et renvoie une image WebP bornée à MAX_SIDE pixels, prête à être stockée (ValidationError sinon)."""
    return reencode_as_webp(upload, MAX_UPLOAD_BYTES, lambda image: shrink_to_fit(image, MAX_SIDE), name='image.webp')
