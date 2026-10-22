"""Administration du catalogue : bières, dégustations, brasseries, bars.

La certification des bars et brasseries se fait depuis « Contenus à valider » (services/moderation).
"""
from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from unfold.admin import ModelAdmin

from ..models import Beer, Drinks, Brewery, Bar, Style, StyleFamily
from ..services.catalog import style_registry
from ..services.catalog.official_images import process_official_image
from ..services.catalog.tasting_photos import process_tasting_photo
from ..services.establishments import removal
from .images import ProcessedImageAdminMixin
from .pending import PendingKpiMixin, pending_unbranded_beer_count, pending_unofficial_style_count


class OfficialImageAdmin(ProcessedImageAdminMixin, ModelAdmin):
    image_processors = {'image': process_official_image}


class BreweryKnownFilter(admin.SimpleListFilter):
    """File de travail du staff : les bières ajoutées sans brasserie, à rattacher à une brasserie existante ou à créer."""
    title = "brasserie"
    parameter_name = 'brewery_known'

    def lookups(self, request, model_admin):
        return [('no', "À rattacher (brasserie inconnue)"), ('yes', "Rattachée")]

    def queryset(self, request, queryset):
        if self.value() == 'no':
            return queryset.filter(brewery__isnull=True)
        if self.value() == 'yes':
            return queryset.filter(brewery__isnull=False)
        return queryset


@admin.register(Beer)
class BeerAdmin(PendingKpiMixin, OfficialImageAdmin):
    pending_label = "bières sans brasserie à rattacher"
    pending_counter = staticmethod(pending_unbranded_beer_count)
    list_display = ('name', 'brewery', 'degree', 'style', 'is_verified', 'is_deleted')
    list_select_related = ('brewery',)
    list_filter = (BreweryKnownFilter, 'is_verified', 'is_deleted')
    search_fields = ('name', 'brewery__name')
    # La brasserie se cherche par nom ou par ville (deux brasseries peuvent porter le même nom) ; le « + » à côté du champ en crée une
    autocomplete_fields = ('brewery',)
    # Le vecteur de recherche du chat IA est calculé par le site (services/catalog/embeddings.py) : l'afficher comme un champ de texte de
    # 1024 nombres invitait à le casser (un envoi vide faisait planter l'enregistrement)
    exclude = ('embedding',)


@admin.register(StyleFamily)
class StyleFamilyAdmin(ModelAdmin):
    """Familles de styles : leur ordre est celui des statistiques ; renommer une famille la renomme partout."""
    list_display = ('name', 'position', 'style_count')
    list_editable = ('position',)
    search_fields = ('name',)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_styles=Count('styles'))

    @admin.display(description="Styles", ordering='_styles')
    def style_count(self, obj):
        return obj._styles


@admin.register(Style)
class StyleAdmin(PendingKpiMixin, ModelAdmin):
    """Référentiel des styles : nom officiel, famille et alias. Les nouvelles saisies suivent tout de suite ; les bières déjà enregistrées
    sont remises à jour par l'action ci-dessous (ou `manage.py normalize_styles`).

    Un style saisi par un membre et absent du référentiel apparaît ici « à valider » (non officiel) : l'équipe le range dans une famille et le
    valide, ou en fait un alias d'un style officiel puis remet les bières à jour (le style devenu inutile disparaît)."""
    pending_label = "styles saisis par des membres, à valider"
    pending_counter = staticmethod(pending_unofficial_style_count)
    list_display = ('name', 'family', 'is_official', 'beer_count')
    list_filter = ('is_official', 'family')
    search_fields = ('name', 'aliases')
    autocomplete_fields = ('family',)
    actions = ['approve', 'renormalize_beers']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('family').annotate(_beers=Count('beer_styles'))

    @admin.display(description="Bières", ordering='_beers')
    def beer_count(self, obj):
        return obj._beers

    @admin.action(description="Valider les styles sélectionnés (leur famille doit être choisie)")
    def approve(self, request, queryset):
        ready = queryset.filter(family__isnull=False)
        skipped = queryset.count() - ready.count()
        updated = ready.update(is_official=True)
        style_registry.forget()
        self.message_user(request, f"{updated} style(s) validé(s).", messages.SUCCESS)
        if skipped:
            self.message_user(request, f"{skipped} style(s) sans famille n'ont pas été validés : choisissez d'abord leur famille.", messages.WARNING)

    @admin.action(description="Remettre à jour les bières existantes avec le référentiel")
    def renormalize_beers(self, request, queryset):
        self.message_user(request, f"{style_registry.rebuild_all()} bière(s) mise(s) à jour.", messages.SUCCESS)


class BreweryDeletionForm(forms.Form):
    """Que faire des bières d'une brasserie supprimée : les transférer (par défaut) ou les supprimer explicitement."""
    TRANSFER, DELETE = 'transfer', 'delete'
    action = forms.ChoiceField(choices=[(TRANSFER, "Transférer ses bières et leurs dégustations vers une autre brasserie"),
                                        (DELETE, "Supprimer aussi ses bières et toutes leurs dégustations")],
                               initial=TRANSFER, widget=forms.RadioSelect)
    target = forms.ModelChoiceField(queryset=Brewery.objects.none(), required=False, label="Brasserie qui reçoit les bières")
    confirm_delete = forms.BooleanField(required=False, label="Je confirme la suppression définitive des bières et des dégustations")

    def __init__(self, *args, brewery, **kwargs):
        super().__init__(*args, **kwargs)
        self.brewery = brewery
        self.fields['target'].queryset = Brewery.objects.exclude(pk=brewery.pk).order_by('name')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('action') == self.TRANSFER and not cleaned.get('target'):
            self.add_error('target', "Choisissez la brasserie qui reçoit les bières.")
        if cleaned.get('action') == self.DELETE and not cleaned.get('confirm_delete'):
            self.add_error('confirm_delete', "Cochez la case pour confirmer.")
        return cleaned


@admin.register(Brewery)
class BreweryAdmin(OfficialImageAdmin):
    list_display = ('name', 'city', 'postal_code', 'is_verified')
    search_fields = ('name', 'city', 'postal_code')
    def delete_view(self, request, object_id, extra_context=None):
        """Une brasserie sans bière se supprime comme d'habitude ; sinon l'équipe choisit le sort de ses bières (voir removal)."""
        brewery = self.get_object(request, object_id)
        if brewery is None or not self.has_delete_permission(request, brewery) or not brewery.beer_set.exists():
            return super().delete_view(request, object_id, extra_context)
        form = BreweryDeletionForm(request.POST or None, brewery=brewery)
        if request.method == 'POST' and form.is_valid():
            try:
                with transaction.atomic():  # la trace n'est gardée que si la suppression aboutit
                    self.log_deletions(request, [brewery])
                    removal.delete_brewery(
                        brewery, transfer_to=form.cleaned_data['target'] if form.cleaned_data['action'] == form.TRANSFER else None,
                        delete_beers=form.cleaned_data['action'] == form.DELETE,
                    )
            except removal.RemovalError as error:
                form.add_error('target', str(error))
            else:
                messages.success(request, f"La brasserie {brewery.name} a été supprimée.")
                return redirect('admin:app_brewery_changelist')
        return TemplateResponse(request, 'admin/brewery_delete.html', {
            **self.admin_site.each_context(request), 'title': f"Supprimer {brewery.name}", 'brewery': brewery, 'form': form,
            'impact': removal.impact(brewery), 'opts': self.model._meta,
        })


admin.site.register(Bar, OfficialImageAdmin)


@admin.register(Drinks)
class DrinksAdmin(ProcessedImageAdminMixin, ModelAdmin):
    image_processors = {'photo': process_tasting_photo}
