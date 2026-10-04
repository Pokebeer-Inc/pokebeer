from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 30

# ASCII uniquement : le pseudo est un identifiant public (URL, formulaires, JSON). Pas de /, virgule, espace,
# guillemet ni caractère Unicode piégeux (homoglyphes, contrôle, bidi). \Z évite que $ accepte un « \n » final.
username_validator = RegexValidator(
    regex=rf'\A[A-Za-z0-9][A-Za-z0-9._-]{{{USERNAME_MIN_LENGTH - 1},{USERNAME_MAX_LENGTH - 1}}}\Z',
    message=(
        f"Le pseudo doit contenir de {USERNAME_MIN_LENGTH} à {USERNAME_MAX_LENGTH} caractères : "
        "lettres sans accent, chiffres, point, tiret ou underscore, et commencer par une lettre ou un chiffre."
    ),
    code='invalid_username',
)

# Liste attendue par ACCOUNT_USERNAME_VALIDATORS (allauth) : l'inscription Google génère des pseudos conformes
USERNAME_VALIDATORS = [username_validator]


# Noms affichés par du JavaScript (autocomplétion) : jamais de balise, quelle que soit la protection côté navigateur.
plain_text_validator = RegexValidator(
    regex=r'\A[^<>]*\Z',
    message="Les caractères < et > ne sont pas autorisés.",
    code='markup_not_allowed',
    flags=0,
)

SIRET_LENGTH = 14
LA_POSTE_SIREN = '356000000'


def validate_siret(value):
    """SIRET = 14 chiffres dont la somme de Luhn est valide ; les établissements de La Poste suivent aussi une règle propre
    (somme des chiffres multiple de 5)."""
    if not (value.isascii() and value.isdigit() and len(value) == SIRET_LENGTH):
        raise ValidationError("Le SIRET doit contenir exactement 14 chiffres.", code='invalid_siret')
    weighted = [int(digit) * (2 if index % 2 == 0 else 1) for index, digit in enumerate(value)]
    valid = sum(d - 9 if d > 9 else d for d in weighted) % 10 == 0
    if value.startswith(LA_POSTE_SIREN):
        valid = valid or sum(map(int, value)) % 5 == 0
    if not valid:
        raise ValidationError("Ce numéro SIRET n'est pas valide.", code='invalid_siret')
