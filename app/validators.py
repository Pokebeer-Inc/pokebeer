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
