"""Annonce d'une modification de la politique de confidentialité à tous les membres (réservée aux superusers)."""
from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import path, reverse
from django.views.decorators.http import require_POST
from unfold.admin import ModelAdmin
from unfold.decorators import display

from ..models import PolicyNotice
from ..services import policy_notice
from ..validators import plain_text_validator


class PolicyNoticeForm(forms.Form):
    summary = forms.CharField(label="Ce qui a changé", max_length=200, strip=True, validators=[plain_text_validator])
    notify_by_email = forms.BooleanField(label="Prévenir aussi par e-mail", required=False)


@admin.register(PolicyNotice)
class PolicyNoticeAdmin(ModelAdmin):
    """Historique en lecture seule ; la publication se fait depuis le tableau de bord (une seule action POST)."""

    list_display = ("created_at", "summary", "notified_count", "email_display", "created_by")
    ordering = ("-created_at",)

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    has_view_permission = lambda self, request, obj=None: self.has_module_permission(request)
    has_add_permission = lambda self, request: False
    has_change_permission = lambda self, request, obj=None: False
    has_delete_permission = lambda self, request, obj=None: False

    @display(description="E-mails")
    def email_display(self, obj):
        if not obj.notify_by_email:
            return "Non demandés"
        return f"{obj.emails_sent} envoyés" + ("" if obj.email_done else " (en cours)")

    def get_urls(self):
        return [path("publish/", self.admin_site.admin_view(require_POST(self.publish_view)), name="app_policynotice_publish"), *super().get_urls()]

    def publish_view(self, request):
        if not self.has_module_permission(request):
            return redirect("admin:index")
        form = PolicyNoticeForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Annonce non envoyée : " + " ; ".join(error for errors in form.errors.values() for error in errors))
        else:
            try:
                notice = policy_notice.publish(form.cleaned_data["summary"], form.cleaned_data["notify_by_email"], request.user)
            except policy_notice.TooManyNotices:
                messages.error(request, "Une annonce vient d'être publiée : attendez avant d'en envoyer une autre.")
            else:
                suffix = " Les e-mails partiront par lots chaque jour." if notice.notify_by_email else ""
                messages.success(request, f"{notice.notified_count} membre(s) notifié(s).{suffix}")
        return redirect(reverse("admin:index"))
