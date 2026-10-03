"""Administration du catalogue : bières, dégustations, brasseries, bars."""
from django.contrib import admin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import path
from unfold.admin import ModelAdmin

from ..models import Beer, Drinks, Brewery, Bar
from ..services.verification import certify_establishment


admin.site.register(Beer)
admin.site.register(Drinks)
admin.site.register(Brewery)


@admin.register(Bar)
class BarAdmin(ModelAdmin):

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "<slug:bar_slug>/verify/",
                self.admin_site.admin_view(
                    self.verify_bar
                ),
                name="bar_verify",
            ),
        ]

        return custom_urls + urls

    def verify_bar(self, request, bar_slug):

        if request.method != "POST":
            return JsonResponse(
                {
                    "success": False,
                    "error": "Méthode non autorisée",
                },
                status=405,
            )

        # Seuls les superusers peuvent valider un bar
        if not request.user.is_superuser:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Permission refusée",
                },
                status=403,
            )

        bar = get_object_or_404(
            Bar,
            slug=bar_slug,
        )

        certify_establishment(bar, request.user)

        return JsonResponse(
            {
                "success": True,
                "bar_slug": bar.slug,
                "is_verified": True,
            }
        )
