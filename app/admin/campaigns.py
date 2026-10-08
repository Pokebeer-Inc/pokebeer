"""Campagnes e-mail (réservées aux superusers) : rédaction, aperçu, test, lancement, envoi par lots et annulation.

Chaque action qui modifie l'état (test, lancement, lot, annulation) est un POST protégé par CSRF ; seul l'aperçu est un GET.
"""
from urllib.parse import urlparse

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.validators import RegexValidator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.views.decorators.http import require_GET, require_POST
from unfold.admin import ModelAdmin
from unfold.decorators import display

from ..models import BeerUser, EmailCampaign
from ..services import campaigns

MIN_ACTIVITY_DAYS, MAX_ACTIVITY_DAYS = 7, 730
single_line = RegexValidator(r'\A[^\r\n]*\Z', message="L'objet doit tenir sur une seule ligne.")


def allowed_link(url):
    """Un bouton ne mène qu'au site (qui s'ouvre dans l'application Android installée) : jamais vers un domaine tiers (hameçonnage depuis un compte admin)."""
    base = urlparse(settings.PUBLIC_BASE_URL)
    parsed = urlparse(url)
    return parsed.scheme == base.scheme and parsed.netloc == base.netloc


class EmailCampaignForm(forms.ModelForm):
    class Meta:
        model = EmailCampaign
        fields = ('subject', 'body', 'cta_label', 'cta_url', 'kind', 'audience', 'activity_days', 'custom_members')
        widgets = {'body': forms.Textarea(attrs={'rows': 10})}
        help_texts = {
            'body': "Texte brut, paragraphes séparés par une ligne vide. {username} est remplacé par le pseudo du membre.",
            'cta_url': "Adresse d'une page du site Pokebeer uniquement ; sur Android elle s'ouvre dans l'application.",
            'activity_days': "Pour « actifs » et « inactifs » : dernière visite il y a moins / plus de ce nombre de jours.",
            'custom_members': "Pour « liste personnalisée » : choisissez les membres (recherche par pseudo ou e-mail). Les promotionnels ne partent pas à ceux qui se sont désinscrits.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'subject' in self.fields:  # absent sur la page d'une campagne lancée (lecture seule)
            self.fields['subject'].validators.append(single_line)
        if 'custom_members' in self.fields:
            self.fields['custom_members'].queryset = BeerUser.objects.filter(is_active=True).order_by('username')
            self.fields['custom_members'].label_from_instance = lambda member: f"{member.username} - {member.email}"

    def clean_activity_days(self):
        days = self.cleaned_data['activity_days']
        if not MIN_ACTIVITY_DAYS <= days <= MAX_ACTIVITY_DAYS:
            raise forms.ValidationError(f"Entre {MIN_ACTIVITY_DAYS} et {MAX_ACTIVITY_DAYS} jours.")
        return days

    def clean(self):
        data = super().clean()
        label, url = data.get('cta_label'), data.get('cta_url')
        if bool(label) != bool(url):
            raise forms.ValidationError("Le bouton demande un texte et un lien, ou aucun des deux.")
        if url and not allowed_link(url):
            self.add_error('cta_url', "Lien refusé : uniquement une page de Pokebeer.")
        if data.get('audience') == EmailCampaign.Audience.CUSTOM:
            chosen = data.get('custom_members')
            if chosen is not None and not chosen:
                self.add_error('custom_members', "Choisissez au moins un membre.")
            elif chosen is not None and len(chosen) > campaigns.MAX_CUSTOM_MEMBERS:
                self.add_error('custom_members', f"{campaigns.MAX_CUSTOM_MEMBERS} membres au plus.")
        return data


@admin.register(EmailCampaign)
class EmailCampaignAdmin(ModelAdmin):
    form = EmailCampaignForm
    change_form_after_template = "admin/campaign_actions.html"
    list_display = ("subject", "kind", "audience", "status_display", "delivery_display", "created_at", "created_by")
    list_filter = ("kind", "audience", "status")
    ordering = ("-created_at",)
    filter_horizontal = ("custom_members",)  # liste de choix avec recherche : « pseudo - e-mail »
    fieldsets = (
        ("Message", {"fields": ("subject", "body", "cta_label", "cta_url")}),
        ("Destinataires", {"fields": ("kind", "audience", "activity_days", "custom_members")}),
    )

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    has_view_permission = lambda self, request, obj=None: self.has_module_permission(request)
    has_add_permission = lambda self, request: self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        # Une campagne lancée est figée : c'est la trace de ce qui a été envoyé
        return self.has_module_permission(request) and (obj is None or obj.status == EmailCampaign.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    @display(description="État", label={"Brouillon": "info", "Envoi en cours": "warning", "Terminée": "success", "Annulée": "danger"})
    def status_display(self, obj):
        return obj.get_status_display()

    @display(description="Envois")
    def delivery_display(self, obj):
        stats = campaigns.stats(obj)
        return f"{stats['Envoyé']} / {stats['total']}" if stats['total'] else "—"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        campaign = self.get_object(request, object_id)
        extra = {}
        if campaign is not None:
            extra = {
                "campaign": campaign, "stats": campaigns.stats(campaign),
                "preview": campaigns.preview(campaign) if campaign.status == EmailCampaign.Status.DRAFT else None,
                "is_draft": campaign.status == EmailCampaign.Status.DRAFT, "is_sending": campaign.status == EmailCampaign.Status.SENDING,
                "daily_limit": settings.CAMPAIGN_EMAIL_DAILY_LIMIT,
            }
        return super().change_view(request, object_id, form_url, {**(extra_context or {}), **extra})

    def get_urls(self):
        wrap = self.admin_site.admin_view
        return [
            path("<int:pk>/preview/", wrap(require_GET(self.preview_view)), name="app_emailcampaign_preview"),
            path("<int:pk>/do/<slug:action>/", wrap(require_POST(self.action_view)), name="app_emailcampaign_action"),
            *super().get_urls(),
        ]

    def _campaign(self, request, pk):
        if not self.has_module_permission(request):
            raise Http404
        return get_object_or_404(EmailCampaign, pk=pk)

    def preview_view(self, request, pk):
        """Le message tel que le recevrait l'administrateur connecté (page HTML de l'e-mail)."""
        campaign = self._campaign(request, pk)
        return HttpResponse(render_to_string("emails/campaign.html", campaigns.email_context(campaign, request.user)))

    def action_view(self, request, pk, action):
        campaign = self._campaign(request, pk)
        handler = {"test": self._test, "launch": self._launch, "batch": self._batch, "cancel": self._cancel}.get(action)
        if handler is None:
            raise Http404
        try:
            handler(request, campaign)
        except campaigns.CampaignError as error:
            messages.error(request, str(error))
        return redirect(reverse("admin:app_emailcampaign_change", args=[campaign.pk]))

    def _test(self, request, campaign):
        sent = campaigns.send_test(campaign, request.user)
        if sent:
            messages.success(request, f"Test envoyé à {request.user.email}.")
        else:
            messages.error(request, "Le test n'a pas pu être envoyé (serveur d'e-mail).")

    def _launch(self, request, campaign):
        if campaign.kind == EmailCampaign.Kind.SERVICE and not request.POST.get("confirm_service"):
            raise campaigns.CampaignError("Confirmez que ce message est indispensable : il partira même aux membres ayant refusé les e-mails.")
        campaign = campaigns.launch(campaign, request.user)
        sent = campaigns.send_batch(campaign, limit=campaigns.ADMIN_BATCH)
        messages.success(request, f"Campagne lancée : {sent} e-mail(s) envoyé(s) maintenant, la suite part par lots chaque jour.")

    def _batch(self, request, campaign):
        if campaign.status != EmailCampaign.Status.SENDING:
            raise campaigns.CampaignError("Cette campagne n'est pas en cours d'envoi.")
        messages.success(request, f"{campaigns.send_batch(campaign, limit=campaigns.ADMIN_BATCH)} e-mail(s) envoyé(s).")

    def _cancel(self, request, campaign):
        campaigns.cancel(campaign)
        messages.success(request, "Campagne annulée : les messages déjà partis ne peuvent pas être rappelés.")
