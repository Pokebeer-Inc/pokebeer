"""Dates lisibles pour les fils d'activité : « aujourd'hui », « hier », « lundi », puis « 12 oct. »."""
from django import template
from django.utils import timezone
from django.utils.formats import date_format

register = template.Library()


@register.filter
def friendly_date(value):
    """`value` est une date (jour de dégustation) ; toute autre valeur est rendue telle quelle."""
    if not hasattr(value, 'toordinal') or hasattr(value, 'hour'):
        return value
    days = (timezone.localdate() - value).days
    if days == 0:
        return "aujourd'hui"
    if days == 1:
        return "hier"
    if 1 < days < 7:
        return date_format(value, 'l')
    return date_format(value, 'j M')
