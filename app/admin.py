from django.contrib import admin, messages
from django.db import models
from django.db.models import Count
from django.contrib.postgres.fields import ArrayField
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils import timezone

from unfold.admin import ModelAdmin
from unfold.contrib.forms.widgets import ArrayWidget, WysiwygWidget
from unfold.decorators import display

from .models import BeerUser, Beer, Drinks, Brewery, Report, Bar
from .models import Notification, Feedback

from .forms import ReportAdminForm, FeedbackAdminForm
from .services.realtime_service import broadcast_notifications


@admin.register(BeerUser)
class BeerUserAdmin(ModelAdmin):

    list_display = (
        "username",
        "email",
        "created_at",
        "active_display",
    )

    list_filter = (
        "is_active",
        "groups",
        "created_at",
    )

    search_fields = (
        "username",
        "email",
    )

    ordering = (
        "-created_at",
    )

    actions = (
        "suspend_accounts",
        "reactivate_accounts",
    )

    @display(
        description="Statut",
        ordering="is_active",
        label={
            "Actif": "success",
            "Suspendu": "danger",
        },
    )
    def active_display(self, obj):
        return "Actif" if obj.is_active else "Suspendu"

    def is_protected(self, request, user):
        # Un modérateur ne peut ni se suspendre lui-même, ni suspendre un superuser s'il n'en est pas un
        return user.pk == request.user.pk or (user.is_superuser and not request.user.is_superuser)

    def get_readonly_fields(self, request, obj=None):
        readonly = super().get_readonly_fields(request, obj)
        if obj and self.is_protected(request, obj):
            return (*readonly, "is_active")
        return readonly

    @admin.action(description="Suspendre les comptes sélectionnés")
    def suspend_accounts(self, request, queryset):
        self.set_active(request, queryset, False)

    @admin.action(description="Réactiver les comptes sélectionnés")
    def reactivate_accounts(self, request, queryset):
        self.set_active(request, queryset, True)

    def set_active(self, request, queryset, active):
        allowed = [user.pk for user in queryset if not self.is_protected(request, user)]
        updated = BeerUser.objects.filter(pk__in=allowed).update(is_active=active)
        self.message_user(request, f"{updated} compte(s) {'réactivé(s)' if active else 'suspendu(s)'}.", messages.SUCCESS)

        skipped = queryset.count() - len(allowed)
        if skipped:
            self.message_user(request, f"{skipped} compte(s) ignoré(s) : votre propre compte ou un superuser.", messages.WARNING)


admin.site.register(Beer)
admin.site.register(Drinks)
admin.site.register(Brewery)


@admin.register(Bar)
class BarAdmin(ModelAdmin):

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "<int:bar_id>/verify/",
                self.admin_site.admin_view(
                    self.verify_bar
                ),
                name="bar_verify",
            ),
        ]

        return custom_urls + urls

    def verify_bar(self, request, bar_id):

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
            pk=bar_id,
        )

        bar.is_verified = True
        bar.verified_by = request.user
        bar.verified_at = timezone.now()

        bar.save(
            update_fields=[
                "is_verified",
                "verified_by",
                "verified_at",
            ]
        )

        return JsonResponse(
            {
                "success": True,
                "bar_id": bar.id,
                "is_verified": True,
            }
        )


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
class ReportAdmin(ModelAdmin):

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

        notif = Notification.objects.create(
            recipient=obj.reporter,
            sender=None,
            notif_type="report_updated",
            report=obj,
        )

        broadcast_notifications([notif])


@admin.register(Feedback)
class FeedbackAdmin(ModelAdmin):

    class Media:
        js = (
            "script/admin_link_line.js",
        )

    form = FeedbackAdminForm

    compressed_fields = False
    warn_unsaved_form = True

    # L'admin ne peut pas modifier le message original de l'utilisateur
    readonly_fields = (
        "user",
        "message",
        "created_at",
    )

    fieldsets = (
        (
            "Suggestions",
            {
                "fields": (
                    "user",
                    "message",
                    "created_at",
                ),
            },
        ),
        (
            "Traitement",
            {
                "fields": (
                    "status",
                    "admin_reply",
                ),
            },
        ),
    )

    list_display = (
        "user",
        "status_display",
        "created_at_display",
    )

    list_filter = (
        "status",
        "created_at",
    )

    search_fields = (
        "user__username",
        "message",
        "admin_reply",
    )

    @display(
        description="Statut",
        ordering="status",
        label={
            "En attente": "info",
            "Répondu": "success",
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

    def save_model(self, request, obj, form, change):

        super().save_model(
            request,
            obj,
            form,
            change,
        )

        # Si on est en modification, que la réponse admin
        # a été modifiée et n'est pas vide
        if change and "admin_reply" in form.changed_data and obj.admin_reply:

            obj.status = "replied"
            obj.save()

            # On génère la notification et on l'envoie via WebSockets
            notif = Notification.objects.create(
                recipient=obj.user,
                sender=None,
                notif_type="feedback_replied",
                feedback=obj,
            )

            broadcast_notifications([notif])


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
            "id",
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
            args=[bar["id"]],
        )

    context.update({
        "beer_count_by_style": list(beer_count_by_style),

        "kpi_users": BeerUser.objects.count(),

        "kpi_beers": Beer.objects.count(),

        "kpi_brewery": Brewery.objects.count(),

        "kpi_report": Report.objects.count(),

        "bars": bars,
    })

    return context