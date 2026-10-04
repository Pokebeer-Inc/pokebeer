"""Contrôle commun des images envoyées par les membres : taille, format réel (jamais le type déclaré) et dimensions."""
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

MAX_SOURCE_PIXELS = 25_000_000  # protège contre les « bombes de décompression »
MIME_TYPES = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}


def open_image(upload, max_bytes):
    """Ouvre l'image envoyée après avoir vérifié sa taille, son format réel et ses dimensions (ValidationError sinon)."""
    if upload.size > max_bytes:
        raise ValidationError(f"L'image est trop lourde (maximum {max_bytes // (1024 * 1024)} Mo).", code='too_large')
    try:
        image = Image.open(upload)
        if image.format not in MIME_TYPES:
            raise ValidationError("Format non pris en charge : utilisez une image JPEG, PNG ou WebP.", code='bad_format')
        if image.width * image.height > MAX_SOURCE_PIXELS:
            raise ValidationError("Les dimensions de l'image sont trop grandes.", code='too_many_pixels')
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError("Ce fichier n'est pas une image valide.", code='invalid_image') from None
    return image
