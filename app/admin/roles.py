"""Gestion des rôles dans l'admin : page dédiée, journalisation via LogEntry (table Django existante)."""
from django.contrib import messages
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db import models, transaction
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from unfold.decorators import display

from ..models import BeerUser
from ..services.roles import ADMIN, LOCKED_ROLES, ROLES, grant_role, revoke_role, role_counts, role_q, user_roles

LOG_PREFIX = "Rôle "
SELF_PROTECTED_ROLES = {ADMIN, "staff"}
# Champs de droits : modifiables uniquement via la page Rôles (jamais depuis le formulaire utilisateur)
PRIVILEGE_FIELDS = ("groups", "is_superuser")
SUPERUSER_ONLY_FIELDS = ("user_permissions",)


class RoleManagementMixin:
    """À mélanger à BeerUserAdmin : colonne, page « Rôles » et verrouillage des champs de droits."""

    # --- Formulaire utilisateur : aucun contournement de la page Rôles ---
    def get_readonly_fields(self, request, obj=None):
        readonly = (*super().get_readonly_fields(request, obj), *PRIVILEGE_FIELDS)
        if not request.user.is_superuser:
            readonly += SUPERUSER_ONLY_FIELDS
        return tuple(dict.fromkeys(readonly))

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("groups")

    @display(description="Rôles", label=True)
    def roles_display(self, obj):
        return [ROLES[key][0] for key in user_roles(obj)]

    # --- Page « Rôles » ---
    def get_urls(self):
        view = require_http_methods(["GET", "POST"])(self.roles_view)
        return [path("roles/", self.admin_site.admin_view(view), name="app_beeruser_roles"), *super().get_urls()]

    def roles_view(self, request):
        if not self.has_view_permission(request):
            return redirect("admin:index")
        if request.method == "POST":
            return self._update_role(request)
        return TemplateResponse(request, "admin/roles.html", self._page_context(request))

    def _page_context(self, request):
        role = request.GET.get("role", "")
        q = request.GET.get("q", "").strip()
        users = BeerUser.objects.prefetch_related("groups").order_by("username")
        if role in ROLES:
            users = users.filter(role_q(role))
        if q:
            users = users.filter(models.Q(username__icontains=q) | models.Q(email__icontains=q))

        counts = role_counts(BeerUser.objects.all())
        tabs = [{"key": key, "label": label, "description": desc, "count": counts[key]} for key, (label, _, desc) in ROLES.items()]
        page = Paginator(users, 25).get_page(request.GET.get("page"))
        rows = [{"user": user, "cells": self._cells(request, user, tabs)} for user in page]
        return {
            **self.admin_site.each_context(request),
            "title": "Rôles", "tabs": tabs, "rows": rows, "page": page, "role": role, "q": q,
            "total": BeerUser.objects.count(), "can_edit": request.user.is_superuser,
            "history": self._history(),
        }

    @staticmethod
    def _cells(request, user, tabs):
        owned = user_roles(user)
        return [{
            "key": tab["key"], "label": tab["label"], "has": tab["key"] in owned,
            "locked": tab["key"] in LOCKED_ROLES,
            "self_lock": user.pk == request.user.pk and tab["key"] in SELF_PROTECTED_ROLES,
        } for tab in tabs]

    @staticmethod
    def _history():
        return (
            LogEntry.objects
            .filter(content_type=ContentType.objects.get_for_model(BeerUser), change_message__startswith=LOG_PREFIX)
            .select_related("user")[:10]
        )

    # --- Modification (POST) : refus explicite avant toute écriture ---
    def _refusal(self, request, user, key, op):
        if not request.user.is_superuser:
            return "Seuls les admins peuvent gérer les rôles."
        if not user or key not in ROLES or op not in ("add", "remove"):
            return "Demande invalide."
        if op == "remove" and key in LOCKED_ROLES:
            return "Le rôle Contributeur est conservé pour tous les membres."
        if op == "remove" and user.pk == request.user.pk and key in SELF_PROTECTED_ROLES:
            return "Vous ne pouvez pas vous retirer vos propres droits d'administration."
        return None

    def _update_role(self, request):
        key, op = request.POST.get("role"), request.POST.get("op")
        user = BeerUser.objects.filter(pk=request.POST.get("user") or None).first()

        if refusal := self._refusal(request, user, key, op):
            messages.error(request, refusal)
        else:
            label = ROLES[key][0]
            with transaction.atomic():
                (grant_role if op == "add" else revoke_role)(user, key)
                self.log_change(request, user, f"{LOG_PREFIX}{label} {'attribué' if op == 'add' else 'retiré'}")
            messages.success(request, f"Rôle {label} {'attribué à' if op == 'add' else 'retiré à'} {user.username}.")

        target = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            target = reverse("admin:app_beeruser_roles")
        return redirect(target)
