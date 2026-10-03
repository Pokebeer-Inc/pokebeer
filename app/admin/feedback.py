"""Administration des feedbacks."""
from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.decorators import display

from ..models import Feedback
from ..forms import FeedbackAdminForm
from ..services.notifications import notify


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
            notify("feedback_replied", [obj.user], feedback=obj)
