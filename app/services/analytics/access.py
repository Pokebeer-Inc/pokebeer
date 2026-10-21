"""Qui peut lire les analytics d'un établissement.

Une seule règle, appelée par toutes les vues : l'équipe (staff, super-utilisateur) lit tout ; un gérant lit uniquement les établissements qu'il gère
(relation `managers`, source de vérité des droits, jamais le seul groupe Brasseur ou Bartender). Un autre membre, et un compte suspendu, n'a aucun
accès. Un établissement hors de portée répond comme un établissement inexistant (404) : on ne révèle pas ce qui existe.

C'est ici que viendra se brancher un abonnement payant (un test de plus dans `can_view`), sans toucher aux vues ni aux rapports.
"""
from django.http import Http404

from ..establishments.places import BAR, BREWERY, PLACE_KINDS_BY_KEY
from ..establishments.team import is_manager
from .bar_report import BarReport
from .brewery_report import BreweryReport

REPORTS = {BREWERY.key: BreweryReport, BAR.key: BarReport}


def is_team(user):
    return user.is_authenticated and user.is_active and (user.is_staff or user.is_superuser)


def can_view(user, place):
    return user.is_authenticated and user.is_active and (is_team(user) or is_manager(user, place))


def managed_places(user):
    """[(type d'établissement, établissement)] gérés par le membre : brasseries puis bars, par nom."""
    if not (user.is_authenticated and user.is_active):
        return []
    return [(BREWERY, place) for place in user.managed_breweries.order_by('name')] + [(BAR, place) for place in user.managed_bars.order_by('name')]


def get_viewable_place(user, kind_key, slug):
    """L'établissement demandé, ou Http404 s'il n'existe pas, si le type est inconnu ou si le membre n'a pas le droit de le lire."""
    kind = PLACE_KINDS_BY_KEY.get(kind_key)
    place = kind.model.objects.filter(slug=slug).first() if kind else None
    if place is None or not can_view(user, place):
        raise Http404
    return kind, place
