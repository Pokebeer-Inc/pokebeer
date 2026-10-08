"""Filtres et tri des brasseries et des bars : ville, vérifiés, style de bière brassé ; tri par nom ou par date d'ajout.

La ville n'a pas de colonne : elle est lue dans l'adresse (« 2 Quai de la Fosse, 44000 Nantes » -> « Nantes ») par la base,
avec la même insensibilité aux accents et à la casse que la recherche.
"""
from django.db.models import CharField, Func, Value
from django.db.models.functions import Trim

from ..models import Beer
from . import search

CITY_PATTERN = r'[0-9]{4,5}[[:space:]]+([^,]+)'  # code postal (4 ou 5 chiffres) suivi de la ville
MAX_VALUE_LENGTH = 100
PARAMS = ('city', 'verified', 'style', 'sort')
SORTS = {  # même vocabulaire que le tri des bières ; `id` suit l'ordre d'ajout
    'date_desc': ('-id',),
    'date_asc': ('id',),
    'name_asc': ('name', 'id'),
    'name_desc': ('-name', 'id'),
}


def city_expression():
    """Ville extraite de l'adresse (NULL si l'adresse n'a pas de code postal)."""
    extracted = Func('address', Value(CITY_PATTERN), function='SUBSTRING', arg_joiner=' FROM ', template='%(function)s(%(expressions)s)', output_field=CharField())
    return Trim(extracted)


def cities(model):
    """Villes proposées par le filtre : une par ville distincte (accents et casse ignorés), triées."""
    names = model.objects.annotate(_city=city_expression()).exclude(_city__isnull=True).exclude(_city='').values_list('_city', flat=True).distinct()
    unique = {}
    for name in sorted(names, key=search.normalize):
        unique.setdefault(search.normalize(name), name)
    return list(unique.values())


def is_filtered(params):
    return any(params.get(name) for name in PARAMS)


def ordering(params, default):
    """Champs de tri : celui demandé (valeur inconnue ignorée), sinon l'ordre par défaut (pertinence d'abord)."""
    return SORTS.get(params.get('sort'), default)


def apply(queryset, params, kind):
    """Restreint les établissements de `kind` (PlaceKind) selon les paramètres de la requête ; un paramètre inconnu est ignoré."""
    city = (params.get('city') or '').strip()[:MAX_VALUE_LENGTH]
    if city:
        queryset = queryset.annotate(_city_key=search.indexed(city_expression())).filter(_city_key=search.normalize(city))
    if params.get('verified'):
        queryset = queryset.filter(is_verified=True)
    style = (params.get('style') or '').strip()[:MAX_VALUE_LENGTH]
    if style and kind.key == 'brewery':
        queryset = queryset.filter(pk__in=Beer.objects.filter(is_deleted=False, style__icontains=style).values('brewery_id'))
    return queryset
