"""Tableau de bord de l'admin."""

from django.db.models import Count

from ..models import BeerUser, Beer, Brewery, Report
from ..services.places_map import places_for_map
from ..services.roles import role_counts


def dashboard_callback(request, context):

    beer_count_by_style = (
        Beer.objects
        .filter(is_deleted=False)
        .exclude(style__isnull=True)
        .exclude(style="")
        .values("style")
        .annotate(nb_bieres=Count("id"))
        .order_by("style")
    )

    context.update({
        "beer_count_by_style": list(beer_count_by_style),

        "kpi_users": BeerUser.objects.count(),

        "kpi_roles": role_counts(BeerUser.objects.all()),

        "kpi_beers": Beer.objects.count(),

        "kpi_brewery": Brewery.objects.count(),

        "kpi_report": Report.objects.count(),

        "places": places_for_map(),

    })

    return context
