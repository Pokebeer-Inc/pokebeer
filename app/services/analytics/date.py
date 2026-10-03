"""Filtres par date calendaire."""
from django.db import models


def date_range(queryset, field_name, start, end=None):
    """Filtre par date calendaire, que le champ soit un DateField ou un DateTimeField (pas de datetime naïf)."""
    lookup = f'{field_name}__date' if isinstance(queryset.model._meta.get_field(field_name), models.DateTimeField) else field_name
    queryset = queryset.filter(**{f'{lookup}__gte': start})
    return queryset.filter(**{f'{lookup}__lt': end}) if end else queryset
