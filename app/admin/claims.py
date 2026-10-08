"""File des revendications d'établissement (superusers) : examen du SIRET contrôlé automatiquement, puis acceptation ou refus motivé.

Lecture seule : une demande n'est jamais modifiée, seulement acceptée ou refusée par un POST protégé par CSRF (jamais par un GET). Accepter
ajoute le membre aux gérants et lui donne son rôle ; refuser exige un motif, communiqué au demandeur par e-mail et notification.
"""
from django.contrib import admin, messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.views.decorators.http import require_POST
from unfold.admin import ModelAdmin
from unfold.decorators import display

from ..models import EstablishmentClaim
from ..services import claims

Status = EstablishmentClaim.Status
ACTIONS = ('approve', 'reject')


@admin.register(EstablishmentClaim)
class EstablishmentClaimAdmin(ModelAdmin):
    change_form_after_template = "admin/claim_actions.html"
    list_display = ("claimant", "place_display", "kind_display", "siret", "check_display", "status_display", "created_at")
    list_filter = ("status",)
    search_fields = ("claimant__username", "siret", "brewery__name", "bar__name")
    ordering = ("-created_at",)
    readonly_fields = ("claimant", "place_display", "siret", "message", "status", "created_at", "decided_at", "decided_by", "reason")
    fields = readonly_fields

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    has_view_permission = lambda self, request, obj=None: self.has_module_permission(request)
    has_add_permission = lambda self, request: False
    has_change_permission = lambda self, request, obj=None: False
    has_delete_permission = lambda self, request, obj=None: False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("claimant", "brewery", "bar", "decided_by")

    def changelist_view(self, request, extra_context=None):
        # Par défaut, ce qui attend une décision : l'historique reste à un clic (filtre « Tous »)
        if not request.GET:
            return redirect(f"{request.path}?status__exact={Status.PENDING}")
        return super().changelist_view(request, extra_context)

    @display(description="Fiche")
    def place_display(self, obj):
        place = obj.place
        locality = " ".join(part for part in (place.postal_code, place.city) if part)
        return f"{place.name} ({locality})" if locality else place.name

    @display(description="Type")
    def kind_display(self, obj):
        return "Brasserie" if obj.brewery_id else "Bar"

    @display(description="Contrôle SIRET", label={"OK": "success", "À vérifier": "warning", "Indisponible": "info"})
    def check_display(self, obj):
        registry = obj.registry or {}
        if not registry.get("available", True):
            return "Indisponible"
        return "OK" if registry.get("found") and registry.get("active") and registry.get("activity_ok") and registry.get("postal_match") else "À vérifier"

    @display(description="État", label={"En attente": "warning", "Acceptée": "success", "Refusée": "danger", "Annulée par le demandeur": "info"})
    def status_display(self, obj):
        return obj.get_status_display()

    def change_view(self, request, object_id, form_url="", extra_context=None):
        claim = self.get_object(request, object_id)
        extra = {}
        if claim is not None:
            place = claim.place
            extra = {
                "claim": claim, "registry": claim.registry or {}, "place": place, "is_pending": claim.is_pending,
                "managers": place.managers.all(), "place_admin_url": reverse(f"admin:app_{claim.kind_key}_change", args=[place.pk]),
                "claimant_admin_url": reverse("admin:app_beeruser_change", args=[claim.claimant_id]),
            }
        return super().change_view(request, object_id, form_url, {**(extra_context or {}), **extra})

    def get_urls(self):
        return [path("<int:pk>/do/<slug:action>/", self.admin_site.admin_view(require_POST(self.action_view)), name="app_establishmentclaim_action"), *super().get_urls()]

    def action_view(self, request, pk, action):
        if not self.has_module_permission(request) or action not in ACTIONS:
            raise Http404
        claim = get_object_or_404(EstablishmentClaim, pk=pk)
        try:
            if action == "approve":
                claims.approve(claim, request.user)
                messages.success(request, f"{claim.claimant.username} gère désormais {claim.place.name} : il en est informé.")
            else:
                claims.reject(claim, request.user, request.POST.get("reason", ""))
                messages.success(request, "Demande refusée : le motif a été communiqué au demandeur.")
        except claims.ClaimError as error:
            messages.error(request, str(error))
        return redirect(reverse("admin:app_establishmentclaim_change", args=[claim.pk]))
