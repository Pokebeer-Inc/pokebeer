"""Page « Contenus à valider » : relecture a posteriori des créations/modifications publiques (ne bloque rien)."""
from django.contrib import admin, messages
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from unfold.admin import ModelAdmin

from ..models import ModerationEntry
from ..services.moderation.actions import NOTE_MAX_LENGTH, REMOVAL_REASONS, ModerationError, amend_and_validate, remove_content, validate_entry
from ..services.moderation.content import CONTENT_TYPES
from ..services.moderation.editing import edit_form
from ..services.moderation.suggestions import apply_suggestion, dismiss_suggestion, proposed_values

PAGE_SIZE = 15
Kind, Action = ModerationEntry.Kind, ModerationEntry.Action
FORM_CSS = 'mt-1 block w-full rounded-default border border-base-200 px-3 py-2 dark:border-base-700 dark:bg-base-900'


def pending_count(request):
    """Pastille du menu latéral."""
    return ModerationEntry.objects.pending().count()


@admin.register(ModerationEntry)
class ModerationEntryAdmin(ModelAdmin):
    """Aucun CRUD Django : tout passe par la page dédiée et ses deux actions POST."""

    def has_module_permission(self, request):
        return self._is_moderator(request)

    def has_view_permission(self, request, obj=None):
        return self._is_moderator(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @staticmethod
    def _is_moderator(request):
        return request.user.is_active and request.user.is_staff

    def get_urls(self):
        def post_only(view):
            return self.admin_site.admin_view(require_POST(view))

        return [
            path("<int:entry_id>/validate/", post_only(self.validate_view), name="app_moderationentry_validate"),
            path("<int:entry_id>/remove/", post_only(self.remove_view), name="app_moderationentry_remove"),
            path("<int:entry_id>/amend/", post_only(self.amend_view), name="app_moderationentry_amend"),
            path("<int:entry_id>/apply/", post_only(self.apply_view), name="app_moderationentry_apply"),
            path("<int:entry_id>/dismiss/", post_only(self.dismiss_view), name="app_moderationentry_dismiss"),
            *super().get_urls(),
        ]

    # --- Page de relecture (remplace la liste Django) ---
    def changelist_view(self, request, extra_context=None):
        if not self._is_moderator(request):
            return redirect("admin:index")
        return TemplateResponse(request, "admin/moderation.html", self._page_context(request))

    def _page_context(self, request):
        kind = request.GET.get("kind", "")
        action = request.GET.get("action", "")
        done = request.GET.get("state") == "done"

        base = ModerationEntry.objects.filter(reviewed_at__isnull=not done)

        counts = {(row["kind"], row["action"]): row["n"] for row in base.values("kind", "action").annotate(n=Count("pk"))}
        entries = base
        if kind in CONTENT_TYPES:
            entries = entries.filter(kind=kind)
        if action in Action.values:
            entries = entries.filter(action=action)
        entries = entries.select_related("reviewed_by", "suggested_by")

        page = Paginator(entries, PAGE_SIZE).get_page(request.GET.get("page"))
        return {
            **self.admin_site.each_context(request),
            "title": "Contenus à valider",
            "cards": self._cards(request, page),
            "page": page,
            "kind": kind, "action": action, "done": done,
            "kind_tabs": [
                {"key": value, "label": label, "count": sum(n for (k, _), n in counts.items() if k == value)}
                for value, label in Kind.choices
            ],
            "action_tabs": [
                {"key": value, "label": label, "count": sum(n for (_, a), n in counts.items() if a == value)}
                for value, label in Action.choices
            ],
            "total": sum(counts.values()),
            "reasons": REMOVAL_REASONS, "note_max": NOTE_MAX_LENGTH,
        }

    @staticmethod
    def _cards(request, page):
        # Une requête par type (in_bulk) plutôt qu'une par entrée
        targets = {
            kind: CONTENT_TYPES[kind].model.objects.in_bulk({e.object_id for e in page if e.kind == kind})
            for kind in {e.kind for e in page}
        }
        cards = []
        for entry in page:
            content = CONTENT_TYPES[entry.kind]
            target = targets[entry.kind].get(entry.object_id)
            suggestion = entry.action == Action.SUGGESTED
            cards.append({
                "entry": entry,
                "suggestion": suggestion,
                # Suggestion : le formulaire de la fiche, pré-rempli avec les valeurs proposées, que l'équipe peut ajuster avant d'appliquer
                # Le formulaire de la fiche (suggestion : pré-rempli avec les valeurs proposées ; création ou modification : valeurs actuelles),
                # que l'équipe peut ajuster avant de valider
                "form": edit_form(
                    content, instance=target, initial=proposed_values(entry) if suggestion else None, css=FORM_CSS, auto_id=f"entry{entry.pk}_%s",
                ) if target is not None and content.suggest_fields and not entry.reviewed_at and content.can_amend(request.user) else None,
                "can_decide": suggestion and content.can_amend(request.user),
                "target_missing": target is None,
                "url": content.url(target) if target else "",
                "authors": [a.username for a in content.authors(target)] if target else [],
                "can_validate": content.can_validate(entry, request.user),
                "certifies": content.certifies(entry, request.user),
                "can_remove": target is not None and content.can_remove_by(entry, request.user),
                "remove_label": content.remove_label_for(entry),
                "cascade_warning": content.cascade_warning(target) if target else "",
            })
        return cards

    # --- Actions ---
    def validate_view(self, request, entry_id):
        return self._run(request, lambda: validate_entry(entry_id, request.user), "Validé.")

    def amend_view(self, request, entry_id):
        return self._run(request, lambda: amend_and_validate(entry_id, request.user, request.POST), "Modifié et validé.")

    def apply_view(self, request, entry_id):
        return self._run(request, lambda: apply_suggestion(entry_id, request.user, request.POST), "Suggestion appliquée.")

    def dismiss_view(self, request, entry_id):
        return self._run(request, lambda: dismiss_suggestion(entry_id, request.user), "Suggestion refusée.")

    def remove_view(self, request, entry_id):
        return self._run(
            request,
            lambda: remove_content(entry_id, request.user, request.POST.get("reason"), request.POST.get("note")),
            "Contenu retiré, l'auteur a été notifié.",
        )

    def _run(self, request, operation, success_message):
        try:
            operation()
            messages.success(request, success_message)
        except ModerationError as error:
            messages.error(request, str(error))
        target = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            target = reverse("admin:app_moderationentry_changelist")
        return redirect(target)
