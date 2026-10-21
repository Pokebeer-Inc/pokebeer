"""Nombres affichés dans les blocs : virgule décimale française, comme partout ailleurs dans l'administration (réglage de langue du site)."""
from django.utils.formats import number_format


def fr(value, decimals=None, signed=False):
    """Nombre avec la virgule française. `decimals` fixe le nombre de décimales (None : celles du nombre) ; `signed` ajoute + aux positifs."""
    text = number_format(value, decimal_pos=decimals)
    return f'+{text}' if signed and value > 0 else text


def euros(value):
    return f'{fr(value, 2)} €'
