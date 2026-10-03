"""Administration des signalements."""
from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.decorators import display

from ..models import Report
from ..forms import ReportAdminForm
from ..services.notifications import notify
from .pending import PendingKpiMixin, pending_report_count


class ReportTargetFilter(admin.SimpleListFilter):

    title = "Type de signalement"
    parameter_name = "target_type"

    def lookups(self, request, model_admin):
        return (
            ("beer", "Bière"),
            ("drink", "Note"),
            ("user", "Utilisateur"),
            ("brewery", "Brasserie"),
        )

    def queryset(self, request, queryset):

        value = self.value()

        if value == "beer":
            return queryset.filter(
                reported_beer__isnull=False
            )

        if value == "drink":
            return queryset.filter(
                reported_drink__isnull=False
            )

        if value == "user":
            return queryset.filter(
                reported_user__isnull=False
            )

        if value == "brewery":
            return queryset.filter(
                reported_brewery__isnull=False
            )

        return queryset


@admin.register(Report)
class ReportAdmin(PendingKpiMixin, ModelAdmin):
    pending_label = "signalements à traiter"
    pending_counter = staticmethod(pending_report_count)

    class Media:
        js = (
            "script/admin_link_line.js",
        )

    form = ReportAdminForm

    compressed_fields = False
    warn_unsaved_form = True

    readonly_fields = (
        "reporter",
        "target_readonly",
        "reason",
        "description",
        "created_at",
    )

    fieldsets = (
        (
            "Signalement",
            {
                "fields": (
                    "reporter",
                    "target_readonly",
                    "reason",
                    "description",
                    "created_at",
                ),
            },
        ),
        (
            "Traitement",
            {
                "fields": (
                    "status",
                    "admin_response",
                ),
            },
        ),
    )

    list_display = (
        "reporter_display",
        "target_type",
        "target_display",
        "reason_display",
        "status_display",
        "created_at_display",
    )

    list_filter = (
        ReportTargetFilter,
        "status",
        "reason",
        "created_at",
    )

    search_fields = (
        "reporter__username",
        "description",
        "admin_response",
    )

    ordering = (
        "-created_at",
    )

    @display(
        description="Utilisateur",
        ordering="reporter__username",
    )
    def reporter_display(self, obj):
        return obj.reporter.username

    @display(description="Cible")
    def target_display(self, obj):
        return self.get_target(obj)

    @display(
        description="Motif",
        ordering="reason",
    )
    def reason_display(self, obj):
        return obj.get_reason_display()

    @display(description="Type")
    def target_type(self, obj):

        if obj.reported_beer:
            return "Bière"

        if obj.reported_drink:
            return "Note"

        if obj.reported_user:
            return "Utilisateur"

        if obj.reported_brewery:
            return "Brasserie"

        return "Inconnu"

    @display(
        description="Statut",
        ordering="status",
        label={
            "Envoyé": "warning",
            "En cours d'examen": "info",
            "Traité": "success",
        },
    )
    def status_display(self, obj):
        return obj.get_status_display()

    @display(
        description="Date",
        ordering="created_at",
    )
    def created_at_display(self, obj):
        return obj.created_at.strftime("%d/%m/%Y %H:%M")

    def get_target(self, obj):

        if obj.reported_beer:
            return f"{obj.reported_beer.name}"

        if obj.reported_drink:
            return f"{obj.reported_drink.drinker_id.username}"

        if obj.reported_user:
            return f"{obj.reported_user.username}"

        if obj.reported_brewery:
            return f"{obj.reported_brewery.name}"

        return "Inconnue"

    @admin.display(description="Cible signalée")
    def target_readonly(self, obj):
        return self.get_target(obj)

    def save_model(self, request, obj, form, change):

        super().save_model(
            request,
            obj,
            form,
            change,
        )

        if not change:
            return

        if not (
            "status" in form.changed_data
            or "admin_response" in form.changed_data
        ):
            return

        notify("report_updated", [obj.reporter], report=obj)
