"""Tableau de bord de l'admin."""

from django.db.models import Count
from django.urls import reverse

from ..models import BeerUser, Beer, Brewery, Report, Bar
from ..services.roles import role_counts


def dashboard_callback(request, context):

    beer_count_by_style = (
        Beer.objects
        .exclude(style__isnull=True)
        .exclude(style="")
        .values("style")
        .annotate(nb_bieres=Count("id"))
        .order_by("style")
    )

    bars = (
        Bar.objects
        .filter(
            latitude__isnull=False,
            longitude__isnull=False,
        )
        .values(
            "slug",
            "name",
            "description",
            "address",
            "phone",
            "email",
            "website",
            "instagram",
            "facebook",
            "siret",
            "latitude",
            "longitude",
            "is_verified",
        )
    )

    # Ajout de l'URL sécurisée de validation pour chaque bar
    bars = list(bars)

    for bar in bars:
        bar["verify_url"] = reverse(
            "admin:bar_verify",
            args=[bar["slug"]],
        )

    context.update({
        "beer_count_by_style": list(beer_count_by_style),

        "kpi_users": BeerUser.objects.count(),

        "kpi_roles": role_counts(BeerUser.objects.all()),

        "kpi_beers": Beer.objects.count(),

        "kpi_brewery": Brewery.objects.count(),

        "kpi_report": Report.objects.count(),

        "bars": bars,
    })

    return context
