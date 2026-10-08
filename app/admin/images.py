"""Images envoyées depuis l'administration : même contrôle et même ré-encodage que sur le site (voir image_form.ProcessedImageMixin).

Sans cela, le formulaire d'administration stockerait le fichier tel quel (format d'origine, métadonnées, dimensions non bornées).
"""
from django import forms

from ..image_form import ProcessedImageMixin


def processed_image_form(image_processors):
    """Formulaire d'administration dont chaque champ image de `image_processors` (nom -> fonction de traitement) est validé et ré-encodé."""
    # `remove_<champ>` est déclaré pour que l'administration le propose (elle n'affiche que les champs déclarés)
    attrs = {f'remove_{name}': forms.BooleanField(required=False, label='Retirer') for name in image_processors}
    return type('ProcessedImageAdminForm', (ProcessedImageMixin, forms.ModelForm), {**attrs, 'image_processors': image_processors})


class ProcessedImageAdminMixin:
    """À placer avant ModelAdmin. `image_processors` : nom du champ image -> fonction de traitement (voir services/official_images.py, tasting_photos.py...)."""
    image_processors = {}

    def get_form(self, request, obj=None, change=False, **kwargs):
        kwargs.setdefault('form', processed_image_form(self.image_processors))
        return super().get_form(request, obj, change=change, **kwargs)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        form.delete_replaced_images()  # l'administration enregistre avec commit=False : l'ancien fichier se retire ici
