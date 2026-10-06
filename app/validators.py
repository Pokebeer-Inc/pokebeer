from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils import timezone

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


# Plafond des textes libres (avis, bio, descriptions) : un TextField n'a aucune limite de lui-même
MAX_TEXT_LENGTH = 2000
MAX_BIO_LENGTH = 500

TASTING_EARLIEST_YEAR = 1900


def validate_tasting_date(value):
    """Une dégustation a eu lieu : ni dans le futur (un jour de marge pour les fuseaux horaires), ni avant 1900."""
    if value > timezone.localdate() + timedelta(days=1):
        raise ValidationError("La date ne peut pas être dans le futur.", code='future_date')
    if value.year < TASTING_EARLIEST_YEAR:
        raise ValidationError("Cette date est trop ancienne.", code='date_too_old')
