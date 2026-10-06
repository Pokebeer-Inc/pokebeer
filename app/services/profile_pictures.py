"""Photos de profil : validation stricte puis ré-encodage, stockage dans un bucket dédié.

Le fichier envoyé n'est jamais conservé tel quel : on le recadre en carré et on le ré-encode en WebP (voir images.reencode_as_webp).
"""
from uuid import uuid4

from django.core.files.storage import storages
from django.utils.functional import LazyObject
from PIL import Image, ImageOps

from .images import delete_stored_file, reencode_as_webp

STORAGE_ALIAS = 'profile_pictures'
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
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
    return reencode_as_webp(
        upload, MAX_UPLOAD_BYTES,
        lambda image: ImageOps.fit(image, (OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS),
        name='avatar.webp',
    )


def delete_stored_picture(name):
    """Supprime l'ancien fichier ; un échec de stockage ne doit jamais casser la requête."""
    delete_stored_file(profile_pictures_storage(), name)
