"""Écran « Doublons probables » (staff) : brasseries et bières du catalogue qui se ressemblent. Détection seulement : la fusion se fait à la main."""
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse

from ..services import catalog_matching


def duplicates_view(request):
    user = request.user
    if not (user.is_active and (user.is_staff or user.is_superuser)):
        raise PermissionDenied
    return TemplateResponse(request, 'admin/duplicates.html', {
        **admin.site.each_context(request), 'title': "Doublons probables",
        'breweries': catalog_matching.duplicate_breweries(),
        'bars': catalog_matching.duplicate_bars(),
        'beers': catalog_matching.duplicate_beers(),
        'limit': catalog_matching.MAX_PAIRS,
    })

