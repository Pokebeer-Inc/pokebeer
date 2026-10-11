"""Codes-barres EAN : validation (longueur et clé de contrôle) et forme normalisée.

Un code lu par la caméra est une saisie comme une autre : seul un code à clé valide, réduit à des chiffres, va plus loin (recherche
dans le catalogue, adresse envoyée à la base de produits).
"""
import re

LENGTHS = (8, 12, 13)  # EAN-8, UPC-A, EAN-13
_DIGITS = re.compile(r'[0-9]+')


def _check_digit(body):
    """Clé de contrôle d'un code sans sa dernière position (poids 3 et 1 en partant de la droite)."""
    total = sum(int(digit) * (3 if index % 2 == 0 else 1) for index, digit in enumerate(reversed(body)))
    return (10 - total % 10) % 10


def normalize(raw):
    """Code sous forme de chiffres (un UPC-A devient un EAN-13 par un zéro initial), ou None s'il n'est pas valide."""
    if not isinstance(raw, str):
        return None
    code = raw.strip()
    if len(code) not in LENGTHS or not _DIGITS.fullmatch(code) or not code.isascii():
        return None
    if int(code[-1]) != _check_digit(code[:-1]):
        return None
    return code.zfill(13) if len(code) == 12 else code
