"""Choix proposés pour le contexte d'une dégustation (lieu, compagnie, format), pour les gabarits."""
from django import template

from ..models import Drinks
from ..validators import MAX_TEXT_LENGTH

register = template.Library()


@register.simple_tag
def tasting_choices():
    return {'venue': Drinks.VenueType.choices, 'company': Drinks.Company.choices, 'format': Drinks.ServingFormat.choices}


@register.simple_tag
def tasting_limits():
    return {'comment': MAX_TEXT_LENGTH}


@register.simple_tag(takes_context=True)
def my_notebooks(context):
    """Carnets du membre connecté, lus une seule fois par requête (une page peut afficher des dizaines de fenêtres de notation)."""
    request = context['request']
    if not hasattr(request, '_my_notebooks'):
        request._my_notebooks = list(request.user.custom_notebooks.all()) if request.user.is_authenticated else []
    return request._my_notebooks
