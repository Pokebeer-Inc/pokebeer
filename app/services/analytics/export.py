"""Export CSV des blocs d'une page d'analytics, avec les filtres courants.

Les libellés (styles, brasseries, villes…) viennent de saisies de membres : toute cellule texte pouvant être interprétée comme
une formule par un tableur est neutralisée (injection de formules CSV, recommandations OWASP).
"""
import csv
import io
import re
import zipfile

from django.http import HttpResponse
from django.utils.text import slugify

FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')
HARMLESS_NUMBER = re.compile(r'^[+-]?\d+([.,]\d+)?\s*%?$')  # « +12 % », « -3,5 » : variations affichées, sans danger
BOM = '﻿'  # pour qu'Excel lise correctement l'UTF-8


def sanitize(cell):
    if cell is None:
        return ''
    if not isinstance(cell, str):
        return cell  # nombres et booléens restent numériques
    if cell.startswith(FORMULA_PREFIXES) and not HARMLESS_NUMBER.match(cell):
        return "'" + cell
    return cell


def block_rows(block):
    """(en-tête, lignes) d'un bloc exportable, ou None pour un bloc sans données tabulaires (KPI, note)."""
    kind = block.block_type
    if kind == 'table':
        return list(block.columns), [list(row) for row in block.rows]
    if kind == 'chart':
        header = ['Catégorie'] + [series['name'] for series in block.series]
        rows = [[category] + [series['data'][index] if index < len(series['data']) else None for series in block.series]
                for index, category in enumerate(block.categories)]
        return header, rows
    if kind == 'map':
        return ['Latitude', 'Longitude', 'Rayon', 'Détail'], [[p['lat'], p['lng'], round(p['radius'], 1), ' | '.join(p['lines'])] for p in block.points]
    return None


def exportable(blocks):
    return [block for block in blocks if block_rows(block) is not None]


def to_csv(block):
    header, rows = block_rows(block)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([sanitize(h) for h in header])
    writer.writerows([sanitize(cell) for cell in row] for row in rows)
    return BOM + buffer.getvalue()


def to_zip(blocks):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for block in exportable(blocks):
            archive.writestr(f'{safe_name(block.id)}.csv', to_csv(block))
    return buffer.getvalue()


def safe_name(value):
    return slugify(str(value))[:80] or 'export'


def response(blocks, target, stem):
    """Téléchargement CSV d'un bloc (`target` = son identifiant) ou ZIP de tous (`target` = 'all'), ou None si le bloc n'existe pas.

    `stem` : début du nom de fichier. Même réponse pour l'administration et pour les gérants."""
    if target == 'all':
        content, content_type, extension, name = to_zip(blocks), 'application/zip', 'zip', stem
    else:
        block = next((b for b in exportable(blocks) if b.id == target), None)
        if block is None:
            return None
        content, content_type, extension, name = to_csv(block), 'text/csv; charset=utf-8', 'csv', f'{stem}-{safe_name(block.id)}'
    reply = HttpResponse(content, content_type=content_type)
    reply['Content-Disposition'] = f'attachment; filename="{name}.{extension}"'
    reply['X-Content-Type-Options'] = 'nosniff'
    reply['Cache-Control'] = 'private, no-store'
    return reply
