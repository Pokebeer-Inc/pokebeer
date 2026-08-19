from django.contrib import admin
from django.db import models
from django.db.models import Count
from django.contrib.postgres.fields import ArrayField
from unfold.admin import ModelAdmin
from unfold.contrib.forms.widgets import ArrayWidget, WysiwygWidget
from unfold.decorators import display
from .models import BeerUser, Beer, Drinks, Brewery, Report, Bar
from .models import Notification, Feedback
from .forms import ReportAdminForm
from .services.realtime_service import broadcast_notifications


admin.site.register(BeerUser)
admin.site.register(Beer)
admin.site.register(Drinks)
admin.site.register(Brewery)
admin.site.register(Bar)


class ReportTargetFilter(admin.SimpleListFilter):
    title = "Type de signalement"
    parameter_name = "target_type"

    def lookups(self, request, model_admin):
        return (
            ("beer", "🍺 Bière"),
            ("drink", "⭐ Note"),
            ("user", "👤 Utilisateur"),
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

        return "Inconnue"

    @admin.display(description="Cible signalée")
    def target_readonly(self, obj):
        return self.get_target(obj)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

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
  #Configuration DjangoUnfold
    readonly_preprocess_fields = {
        "model_field_name": "html.unescape",
        "other_field_name": lambda content: content.strip(),
    }

    formfield_overrides = {
        models.TextField: {
            "widget": WysiwygWidget,
        },
        ArrayField: {
            "widget": ArrayWidget,
        }
    }

    compressed_fields = False
    warn_unsaved_form = True
   
    list_display = ('id', 'user', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'message', 'admin_reply')
    # L'admin ne peut pas modifier le message original de l'utilisateur
    readonly_fields = ('user', 'message', 'created_at')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        
        # Si on est en modification, que la réponse admin a été modifiée et n'est pas vide
        if change and 'admin_reply' in form.changed_data and obj.admin_reply:
            obj.status = 'replied' # On passe le statut en "Répondu"
            obj.save()
            
            # On génère la notification et on l'envoie via WebSockets
            notif = Notification.objects.create(
                recipient=obj.user,
                sender=None, 
                notif_type='feedback_replied',
                feedback=obj
            )
            broadcast_notifications([notif])

def dashboard_callback(request, context):
    beer_count_by_style = (
        Beer.objects
        .exclude(style__isnull=True)
        .exclude(style='')
        .values('style')
        .annotate(nb_bieres=Count('id'))
        .order_by('style')
    )

    kpi_users = (BeerUser.objects.count)
    kpi_beers = (Beer.objects.count)
    kpi_brewery = (Brewery.objects.count)
    kpi_report = (Report.objects.count)

    context.update({
        "beer_count_by_style": list(beer_count_by_style),
        "kpi_users":kpi_users,
        "kpi_beers":kpi_beers,
        "kpi_brewery":kpi_brewery,
        "kpi_report":kpi_report
    })

    return context