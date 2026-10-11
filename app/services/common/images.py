"""Contrôle commun des images envoyées par les membres : taille, format réel (jamais le type déclaré) et dimensions."""
import logging
from io import BytesIO
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

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


def reencode_as_webp(upload, max_bytes, resize, name, quality=85):
    """Valide l'envoi puis le ré-encode en WebP (ValidationError si ce n'est pas une image acceptable).

    Le fichier d'origine n'est jamais conservé : décodé puis ré-encodé, il perd ses métadonnées (EXIF/GPS), ses contenus
    polyglottes et son format. `resize` : fonction Image -> Image qui fixe les dimensions finales.
    """
    image = open_image(upload, max_bytes)
    try:
        image = ImageOps.exif_transpose(image)  # applique l'orientation avant de supprimer les métadonnées
        image = resize(image.convert('RGB'))
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError("Ce fichier n'est pas une image valide.", code='invalid_image') from None

    buffer = BytesIO()
    image.save(buffer, format='WEBP', quality=quality)
    return ContentFile(buffer.getvalue(), name=name)


def delete_stored_file(storage, name):
    """Supprime un fichier du stockage ; un échec de stockage ne doit jamais casser la requête."""
    if not name:
        return
    try:
        storage.delete(name)
    except Exception:
        logger.exception("Suppression du fichier %s impossible", name)


def shrink_to_fit(image, max_side):
    """Borne le grand côté à max_side sans jamais agrandir une petite image (ImageOps.contain l'agrandirait)."""
    if max(image.size) <= max_side:
        return image
    return ImageOps.contain(image, (max_side, max_side), Image.Resampling.LANCZOS)


def random_webp_path(folder):
    """Chemin de stockage aléatoire : le nom du fichier envoyé n'est jamais utilisé (pas de collision ni de chemin imposé)."""
    return f'{folder}/{uuid4().hex}.webp'
