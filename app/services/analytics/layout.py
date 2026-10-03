"""Disposition personnelle des tuiles (ordre, masquage) : stockée en base, par membre et par page.

Choix de persistance : la base, pas le cache. Le cache de Django n'est pas partagé entre les instances serverless et
disparaît à chaque déploiement ; la base survit, suit le membre d'un appareil à l'autre et reste isolée par membre.
Les identifiants reçus du navigateur sont validés (forme, nombre) et ne servent qu'à trier : un identifiant inconnu est ignoré.
"""
import re
from dataclasses import dataclass

from ...models import AnalyticsLayout

ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{0,79}$')
MAX_IDS = 100


@dataclass
class Tile:
    block: object
    hidden: bool = False


def clean_ids(value):
    """Liste d'identifiants valides sans doublon, ou None si l'entrée est incorrecte."""
    if not isinstance(value, list) or len(value) > MAX_IDS:
        return None
    if not all(isinstance(item, str) and ID_PATTERN.match(item) for item in value):
        return None
    return list(dict.fromkeys(value))


def load(user, page_key):
    layout = AnalyticsLayout.objects.filter(user=user, page_key=page_key).first()
    return (layout.order, layout.hidden) if layout else ([], [])


def save(user, page_key, order, hidden):
    """Enregistre la disposition ; une disposition vide revient à celle par défaut (la ligne est supprimée)."""
    if not order and not hidden:
        AnalyticsLayout.objects.filter(user=user, page_key=page_key).delete()
        return
    AnalyticsLayout.objects.update_or_create(user=user, page_key=page_key, defaults={'order': order, 'hidden': hidden})


def _unique_ids(blocks):
    """Deux blocs ne doivent jamais partager un identifiant (sinon l'ordre mémorisé serait ambigu)."""
    seen = {}
    for block in blocks:
        count = seen.get(block.id, 0)
        seen[block.id] = count + 1
        if count:
            block.id = f'{block.id}-{count + 1}'


def arrange(blocks, order, hidden):
    """(notes, tuiles) : notes en tête, tuiles dans l'ordre du membre puis les nouvelles dans l'ordre par défaut."""
    notes = [block for block in blocks if block.block_type == 'note']
    tiles = [block for block in blocks if block.block_type != 'note']
    _unique_ids(tiles)
    position = {block_id: index for index, block_id in enumerate(order)}
    tiles.sort(key=lambda block: position.get(block.id, len(order)))  # tri stable : l'ordre par défaut est conservé
    hidden = set(hidden)
    return notes, [Tile(block, block.id in hidden) for block in tiles]
