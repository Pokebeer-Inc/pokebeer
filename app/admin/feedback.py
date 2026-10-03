"""Administration des échanges avec les membres."""
from django.contrib import admin, messages
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin
from unfold.decorators import display

from ..forms import FeedbackAdminForm
from ..models import Feedback
from ..services import feedback as conversations
from .pending import PendingKpiMixin, pending_feedback_count


@admin.register(Feedback)
class FeedbackAdmin(PendingKpiMixin, ModelAdmin):
    pending_label = "échanges en attente de réponse"
    pending_counter = staticmethod(pending_feedback_count)

    class Media:
        js = (
            "script/admin_link_line.js",
        )

    form = FeedbackAdminForm

    compressed_fields = False
    warn_unsaved_form = True

    # L'équipe ne modifie jamais les messages du membre : elle répond, ce qui ajoute un message à l'échange
    readonly_fields = ("user", "conversation", "created_at")

    fieldsets = (
        ("Échange", {"fields": ("user", "created_at", "conversation")}),
        ("Répondre", {"fields": ("reply",)}),
        ("Traitement", {"fields": ("status",)}),
    )

    list_display = ("user", "status_display", "last_activity_display", "created_at_display")
    list_filter = ("status", "created_at")
    search_fields = ("user__username", "message", "messages__body")
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user").prefetch_related("messages")

    @admin.display(description="Conversation")
    def conversation(self, obj):
        """Tout l'échange, du premier message du membre à la dernière réponse (texte échappé)."""
        if not obj.pk:
            return "—"
        rows = format_html_join(
            "", '<div style="margin:6px 0;padding:8px 12px;border-radius:8px;{}"><strong>{}</strong> '
                '<span style="opacity:.6;font-size:12px">{}</span><div style="white-space:pre-wrap">{}</div></div>',
            (
                ("background:rgba(37,99,235,.12)" if entry.is_team else "background:rgba(128,128,128,.15)",
                 "Équipe" if entry.is_team else obj.user.username,
                 entry.created_at.strftime("%d/%m/%Y %H:%M"), entry.body)
                for entry in conversations.timeline(obj)
            ),
        )
        return format_html('<div style="max-width:720px">{}</div>', rows)

    @display(description="Statut", ordering="status", label={"En attente": "info", "Répondu": "success"})
    def status_display(self, obj):
        return obj.get_status_display()

    @display(description="Dernier message")
    def last_activity_display(self, obj):
        last = conversations.timeline(obj)[-1]
        return f"{'Équipe' if last.is_team else obj.user.username} · {last.created_at.strftime('%d/%m/%Y %H:%M')}"

    @display(description="Ouvert le", ordering="created_at")
    def created_at_display(self, obj):
        return obj.created_at.strftime("%d/%m/%Y %H:%M")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        reply = form.cleaned_data.get("reply")
        if change and reply:
            try:
                conversations.team_reply(obj, request.user, reply)  # message d'équipe + statut « répondu » + notification
            except conversations.FeedbackError as error:
                messages.error(request, str(error))
