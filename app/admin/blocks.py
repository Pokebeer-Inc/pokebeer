"""Visibilité du staff sur les blocages entre membres (lecture seule, réservée aux superusers : données privées)."""
from django.contrib import admin
from django.db.models import Count, OuterRef, Subquery
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.decorators import display

from ..models import Report, UserBlock
from ..services.blocks import REPEATED_BLOCK_THRESHOLD, repeatedly_blocked_count
from .pending import PendingKpiMixin

def _blocks_received():
    """Sous-requête : nombre de membres distincts ayant bloqué `blocked` (ligne courante)."""
    return (
        UserBlock.objects.filter(blocked=OuterRef('blocked'))
        .values('blocked').annotate(n=Count('blocker', distinct=True)).values('n')
    )


class RepeatedlyBlockedFilter(admin.SimpleListFilter):
    title = "Membre bloqué par"
    parameter_name = "blocked_by"

    def lookups(self, request, model_admin):
        return ((str(n), f"au moins {n} membres") for n in (2, REPEATED_BLOCK_THRESHOLD, 5))

    def queryset(self, request, queryset):
        if self.value() and self.value().isdigit():
            return queryset.filter(times_blocked__gte=int(self.value()))
        return queryset


@admin.register(UserBlock)
class UserBlockAdmin(PendingKpiMixin, ModelAdmin):
    pending_label = f"membres bloqués par au moins {REPEATED_BLOCK_THRESHOLD} personnes"
    pending_counter = staticmethod(lambda request: repeatedly_blocked_count())

    list_display = ("blocker_display", "blocked_display", "times_blocked_display", "reports_display", "invited_display", "created_at")
    list_filter = (RepeatedlyBlockedFilter, "blocked__is_active", "created_at")
    search_fields = ("blocker__username", "blocked__username")
    ordering = ("-created_at",)
    list_select_related = ("blocker", "blocked")

    # Lecture seule : le staff observe, il ne modifie pas les blocages des membres
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        reports = (
            Report.objects.filter(reported_user=OuterRef('blocked'))
            .values('reported_user').annotate(n=Count('pk')).values('n')
        )
        return super().get_queryset(request).annotate(
            times_blocked=Subquery(_blocks_received()), reports_received=Subquery(reports),
        )

    @staticmethod
    def _member_link(user):
        return format_html('<a href="{}">{}</a>', reverse('admin:app_beeruser_change', args=[user.pk]), user.username)

    @display(description="A bloqué", ordering="blocker__username")
    def blocker_display(self, obj):
        return self._member_link(obj.blocker)

    @display(description="Membre bloqué", ordering="blocked__username")
    def blocked_display(self, obj):
        suffix = "" if obj.blocked.is_active else " (suspendu)"
        return format_html('{}{}', self._member_link(obj.blocked), suffix)

    @display(description="Bloqué par (total)", ordering="times_blocked")
    def times_blocked_display(self, obj):
        return obj.times_blocked or 0

    @display(description="Invité à signaler", boolean=True, ordering="report_invited_at")
    def invited_display(self, obj):
        return obj.report_invited_at is not None

    @display(description="Signalements reçus", ordering="reports_received")
    def reports_display(self, obj):
        return obj.reports_received or 0
