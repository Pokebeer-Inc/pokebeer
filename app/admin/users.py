"""Administration des membres."""
from django.contrib import admin, messages
from unfold.admin import ModelAdmin
from unfold.decorators import display

from ..models import AccountDeletion, BeerUser
from ..services import inactivity
from ..services.profile_pictures import process_profile_picture
from .images import ProcessedImageAdminMixin
from .roles import RoleManagementMixin


class InactivityFilter(admin.SimpleListFilter):
    title = "Inactivité (RGPD)"
    parameter_name = "inactivity"

    def lookups(self, request, model_admin):
        return (("to_warn", "À prévenir"), ("warned", "Prévenus"), ("due", "À supprimer"))

    def queryset(self, request, queryset):
        pks = {
            "to_warn": inactivity.to_warn,
            "warned": lambda: inactivity.candidates().filter(inactivity_warned_at__isnull=False),
            "due": inactivity.due_for_deletion,
        }.get(self.value())
        return queryset.filter(pk__in=pks().values("pk")) if pks else queryset


@admin.register(BeerUser)
class BeerUserAdmin(ProcessedImageAdminMixin, RoleManagementMixin, ModelAdmin):
    image_processors = {'avatar': process_profile_picture}

    list_display = (
        "username",
        "email",
        "roles_display",
        "created_at",
        "last_activity_at",
        "active_display",
    )

    list_filter = (
        "is_active",
        InactivityFilter,
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


@admin.register(AccountDeletion)
class AccountDeletionAdmin(ModelAdmin):
    """Journal en lecture seule des comptes supprimés (aucune donnée personnelle conservée)."""

    list_display = ("user_id", "reason", "last_activity_at", "was_warned", "deleted_at")
    list_filter = ("reason", "was_warned", "deleted_at")
    ordering = ("-deleted_at",)

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    has_view_permission = lambda self, request, obj=None: self.has_module_permission(request)
    has_add_permission = lambda self, request: False
    has_change_permission = lambda self, request, obj=None: False
    has_delete_permission = lambda self, request, obj=None: False
