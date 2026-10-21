"""Chemins de stockage des fichiers envoyés : toujours aléatoires, le nom du fichier envoyé n'est jamais utilisé (ni collision, ni chemin imposé).

Une fonction par dossier : les migrations référencent ces chemins d'import.
"""
from uuid import uuid4

TASTINGS_DIR = 'tastings'


def random_webp_path(folder):
    return f'{folder}/{uuid4().hex}.webp'


def beer_image_path(instance, filename):
    return random_webp_path('beers')


def brewery_image_path(instance, filename):
    return random_webp_path('breweries')


def bar_image_path(instance, filename):
    return random_webp_path('bars')


def tasting_photo_path(instance, filename):
    return random_webp_path(TASTINGS_DIR)


def profile_picture_path(instance, filename):
    """À la racine du bucket dédié aux photos de profil."""
    return f'{uuid4().hex}.webp'


def spot_photo_path(instance, filename):
    """À la racine du bucket dédié aux photos de souvenirs."""
    return f'{uuid4().hex}.webp'
