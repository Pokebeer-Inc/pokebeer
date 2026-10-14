"""Styles d'une bière : un champ texte qui peut en contenir plusieurs, séparés par des virgules (« IPA, Stout »). Seul endroit qui le découpe."""


def split_styles(value):
    """Styles d'un champ, nettoyés et dans l'ordre, sans doublon ni vide."""
    return list(dict.fromkeys(part.strip() for part in (value or '').split(',') if part.strip()))


def format_styles(value):
    """Saisie d'un membre remise en forme : « ipa ,  stout » donne « Ipa, Stout » (majuscule initiale, sans doublon)."""
    return ", ".join(dict.fromkeys(style.capitalize() for style in split_styles(value)))


def distinct_styles(values):
    """Styles distincts, triés, d'une suite de champs (ex. les valeurs distinctes d'une colonne)."""
    return sorted({style for value in values for style in split_styles(value)})
