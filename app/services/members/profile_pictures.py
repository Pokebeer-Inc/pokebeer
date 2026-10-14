"""Photos de profil : validation stricte puis ré-encodage, stockage dans un bucket dédié.

Le fichier envoyé n'est jamais conservé tel quel : on le recadre en carré et on le ré-encode en WebP (voir images.reencode_as_webp).
"""
from PIL import Image, ImageOps

from ...storages import profile_pictures_storage
from ..common.images import delete_stored_file, reencode_as_webp

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
OUTPUT_SIZE = 512
COOLDOWN_SECONDS = 60


def process_profile_picture(upload):
    """Valide l'envoi et renvoie une image WebP carrée prête à être stockée (ValidationError sinon)."""
    return reencode_as_webp(
        upload, MAX_UPLOAD_BYTES,
        lambda image: ImageOps.fit(image, (OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS),
        name='avatar.webp',
    )


def delete_stored_picture(name):
    """Supprime l'ancien fichier ; un échec de stockage ne doit jamais casser la requête."""
    delete_stored_file(profile_pictures_storage(), name)
