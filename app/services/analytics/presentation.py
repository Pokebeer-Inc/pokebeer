"""Mise en forme d'un tableau pour l'écran des gérants : alignement des nombres, écarts colorés, petites barres de part.

Les blocs (blocks.py) restent indépendants du rendu : ce module lit un tableau déjà calculé et décide seulement comment l'afficher. Aucune donnée
n'est modifiée ni interprétée comme du HTML : le gabarit échappe chaque cellule comme avant.
"""
import re
from dataclasses import dataclass

from .formatting import fr

NUMBER = re.compile(r'^[+\-−]?\d[\d\s.,]*\s?(%|€|j)?$')
HIDDEN_MARK = '<'  # « < 3 » : groupe masqué, aligné comme un nombre
MAX_PERCENT = 100


@dataclass(frozen=True)
class Cell:
    text: str
    numeric: bool = False
    tone: str = ''        # 'up' | 'down' : écart positif ou négatif
    bar: int | None = None  # largeur (0 à 100) de la barre de part, si la colonne en a une


@dataclass(frozen=True)
class PresentedTable:
    columns: list   # [(libellé, aligné à droite)]
    rows: list      # [[Cell]]


def _text(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'Oui' if value else 'Non'
    if isinstance(value, float):
        return fr(value)
    return str(value)


def _is_numeric(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    text = _text(value).strip()
    return text == '—' or text.startswith(HIDDEN_MARK) or bool(NUMBER.match(text))


def _percent_value(text):
    try:
        return float(text.replace('%', '').replace(' ', '').replace(' ', '').replace(',', '.'))
    except ValueError:
        return None


def _tone(text):
    stripped = text.strip()
    if NUMBER.match(stripped) and len(stripped) > 1:
        if stripped.startswith('+'):
            return 'up'
        if stripped[0] in '-−':
            return 'down'
    return ''


def present(block):
    """PresentedTable d'un bloc Table. Une colonne est alignée à droite quand la majorité de ses cellules sont des nombres (la première colonne,
    le libellé de la ligne, reste à gauche)."""
    rows = [list(row) for row in block.rows]
    numeric_columns = []
    for index in range(len(block.columns)):
        values = [row[index] for row in rows if index < len(row)]
        numeric_columns.append(index > 0 and bool(values) and sum(_is_numeric(v) for v in values) * 2 > len(values))
    with_bar = [index for index, label in enumerate(block.columns) if label.startswith('Part') and numeric_columns[index]]

    presented = []
    for row in rows:
        cells = []
        for index, value in enumerate(row):
            text = _text(value)
            numeric = numeric_columns[index] if index < len(numeric_columns) else False
            bar = None
            if index in with_bar and text.endswith('%'):
                share = _percent_value(text)
                bar = round(min(max(share, 0), MAX_PERCENT)) if share is not None else None
            cells.append(Cell(text, numeric, _tone(text) if numeric else '', bar))
        presented.append(cells)
    return PresentedTable([(label, numeric_columns[i]) for i, label in enumerate(block.columns)], presented)
