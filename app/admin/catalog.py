"""Administration du catalogue : bières, dégustations, brasseries, bars.

La certification des bars et brasseries se fait depuis « Contenus à valider » (services/moderation).
"""
from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from unfold.admin import ModelAdmin

from ..models import Beer, Drinks, Brewery, Bar
from ..services.catalog.official_images import process_official_image
from ..services.catalog.tasting_photos import process_tasting_photo
from ..services.establishments import removal
from .images import ProcessedImageAdminMixin


class OfficialImageAdmin(ProcessedImageAdminMixin, ModelAdmin):
    image_processors = {'image': process_official_image}


@admin.register(Beer)
class BeerAdmin(OfficialImageAdmin):
    # Le vecteur de recherche du chat IA est calculé par le site (services/catalog/embeddings.py) : l'afficher comme un champ de texte de
    # 1024 nombres invitait à le casser (un envoi vide faisait planter l'enregistrement)
    exclude = ('embedding',)


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
