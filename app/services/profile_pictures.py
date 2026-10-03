"""Photos de profil : validation stricte puis ré-encodage, stockage dans un bucket dédié.

Le fichier envoyé n'est jamais conservé tel quel : on le décode avec Pillow, on le recadre en carré et on le
ré-encode en WebP. Cela élimine les métadonnées (EXIF/GPS), les contenus polyglottes et les formats non voulus (SVG...).
"""
import logging
from io import BytesIO
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.utils.functional import LazyObject
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

STORAGE_ALIAS = 'profile_pictures'
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_SOURCE_PIXELS = 25_000_000  # protège contre les « bombes de décompression »
ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP'}
OUTPUT_SIZE = 512
COOLDOWN_SECONDS = 60


class _ProfilePictureStorage(LazyObject):
    """Résout le stockage au premier usage (le bucket est lu dans settings.STORAGES)."""

    def _setup(self):
        self._wrapped = storages[STORAGE_ALIAS]


def profile_pictures_storage():
    return _ProfilePictureStorage()


def profile_picture_path(instance, filename):
    """Nom aléatoire : celui du visiteur n'est jamais utilisé (pas de collision ni de chemin imposé)."""
    return f'{uuid4().hex}.webp'


def process_profile_picture(upload):
    """Valide l'envoi et renvoie une image WebP carrée prête à être stockée (ValidationError sinon)."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError(f"L'image est trop lourde (maximum {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo).", code='too_large')
    try:
        image = Image.open(upload)
        if image.format not in ALLOWED_FORMATS:
            raise ValidationError("Format non pris en charge : utilisez une image JPEG, PNG ou WebP.", code='bad_format')
        if image.width * image.height > MAX_SOURCE_PIXELS:
            raise ValidationError("Les dimensions de l'image sont trop grandes.", code='too_many_pixels')
        image = ImageOps.exif_transpose(image)  # applique l'orientation avant de supprimer les métadonnées
        image = ImageOps.fit(image.convert('RGB'), (OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError("Ce fichier n'est pas une image valide.", code='invalid_image') from None

    buffer = BytesIO()
    image.save(buffer, format='WEBP', quality=85)
    return ContentFile(buffer.getvalue(), name='avatar.webp')


def delete_stored_picture(name):
    """Supprime l'ancien fichier ; un échec de stockage ne doit jamais casser la requête."""
    if not name:
        return
    try:
        profile_pictures_storage().delete(name)
    except Exception:
        logger.exception("Suppression de la photo de profil %s impossible", name)
