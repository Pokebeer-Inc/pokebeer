"""Stockages de fichiers nommés (settings.STORAGES), résolus au premier usage : les modèles y font référence sans charger la configuration à l'import."""
from django.core.files.storage import storages
from django.utils.functional import LazyObject

PROFILE_PICTURES = 'profile_pictures'


class _NamedStorage(LazyObject):
    def __init__(self, name):
        super().__init__()
        self.__dict__['_storage_name'] = name

    def _setup(self):
        self._wrapped = storages[self._storage_name]


def profile_pictures_storage():
    """Bucket dédié aux photos de profil (public en lecture)."""
    return _NamedStorage(PROFILE_PICTURES)
