"""Normalisation du texte partagée par la recherche et les clés de comparaison des noms."""
import unicodedata

LIGATURES = str.maketrans({'œ': 'oe', 'æ': 'ae', 'ß': 'ss'})  # absentes des règles de décomposition Unicode


def normalize(text):
    """Minuscules sans accents, comme f_unaccent(lower(...)) côté base."""
    decomposed = unicodedata.normalize('NFKD', (text or '').lower().translate(LIGATURES))
    return ''.join(char for char in decomposed if not unicodedata.combining(char)).strip()
