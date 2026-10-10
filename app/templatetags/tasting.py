"""Choix proposés pour le contexte d'une dégustation (lieu, compagnie, format), pour les gabarits."""
from django import template

from ..models import Drinks

register = template.Library()


@register.simple_tag
def tasting_choices():
    return {'venue': Drinks.VenueType.choices, 'company': Drinks.Company.choices, 'format': Drinks.ServingFormat.choices}
