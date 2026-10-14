import secrets
import string

from django.utils.text import slugify

# Alphabet minuscule : les slugs restent valides pour <slug:...> et insensibles à la casse.
TOKEN_ALPHABET = string.ascii_lowercase + string.digits
# 36^12 ≈ 2^62 combinaisons : impossible à énumérer ou à deviner, collision négligeable.
TOKEN_LENGTH = 12
# Tiret + jeton : ce qui s'ajoute au libellé dans un slug lisible.
SUFFIX_LENGTH = TOKEN_LENGTH + 1


def generate_token(length=TOKEN_LENGTH):
    """Jeton aléatoire issu du CSPRNG du système (module secrets)."""
    return ''.join(secrets.choice(TOKEN_ALPHABET) for _ in range(length))


def generate_slug(label='', max_length=150):
    """
    Slug public non énumérable : « libellé-slugifié-jeton », ou le jeton seul sans libellé exploitable.

    Le jeton aléatoire interdit de deviner ou de parcourir les URLs ; le libellé ne sert qu'à la lisibilité.
    """
    readable = slugify(label)[:max_length - SUFFIX_LENGTH].strip('-')
    token = generate_token()
    return f"{readable}-{token}" if readable else token
