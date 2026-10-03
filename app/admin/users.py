"""Administration des membres."""
from django.contrib import admin, messages
from unfold.admin import ModelAdmin
from unfold.decorators import display

from ..models import BeerUser
from .roles import RoleManagementMixin


@admin.register(BeerUser)
class BeerUserAdmin(RoleManagementMixin, ModelAdmin):

    list_display = (
        "username",
        "email",
        "roles_display",
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
