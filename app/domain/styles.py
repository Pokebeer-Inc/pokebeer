"""Styles d'une bière : un champ texte qui peut en contenir plusieurs, séparés par des virgules (« IPA, Stout »). Seul endroit qui le découpe."""
from .text import normalize


def split_styles(value):
    """Styles d'un champ, nettoyés et dans l'ordre, sans doublon ni vide."""
    return list(dict.fromkeys(part.strip() for part in (value or '').split(',') if part.strip()))


def alias_lines(text):
    """Alias d'un style (un par ligne), nettoyés. Fonction pure : elle sert aussi aux migrations, dont les modèles n'ont pas les propriétés."""
    return [line.strip() for line in (text or '').splitlines() if line.strip()]


def distinct_styles(values):
    """Styles distincts, triés, d'une suite de champs (ex. les valeurs distinctes d'une colonne)."""
    return sorted({style for value in values for style in split_styles(value)})


# Référentiel : un style saisi est ramené à son nom officiel (« ipa », « India Pale Ale » -> « IPA »). Fonctions pures : la table `Style`
# (modifiable par l'équipe) fournit les correspondances, voir services/catalog/style_registry.py.

def style_key(value):
    """Clé de comparaison d'un style : minuscules, sans accents ni espaces superflus (« Ambrée » et « ambree » sont le même style)."""
    return ' '.join(normalize(value).split())


def canonicalize(value, canonical_by_key):
    """Saisie remise en forme avec les noms officiels. `canonical_by_key` : {clé -> nom officiel} (noms et alias).

    Un style inconnu reste accepté (champ libre), simplement mis en forme comme avant ; l'équipe le repère dans les analytics du catalogue."""
    names = (canonical_by_key.get(style_key(style)) or style.capitalize() for style in split_styles(value))
    return ", ".join(dict.fromkeys(names))


def family_of(value, family_by_name):
    """Famille du premier style reconnu d'un champ (« West Coast IPA, IPA » -> « IPA »), ou '' si aucun n'est au référentiel."""
    return next((family_by_name[style] for style in split_styles(value) if style in family_by_name), '')
