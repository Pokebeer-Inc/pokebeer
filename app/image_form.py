"""Champs image des formulaires : envoi validé et ré-encodé, retrait, nettoyage de l'ancien fichier."""
from functools import partial

from django import forms
from django.db import transaction

from .services.images import delete_stored_file

ACCEPTED_TYPES = 'image/jpeg,image/png,image/webp'  # l'iPhone convertit alors le HEIC en JPEG


class ProcessedImageMixin:
    """À placer avant ModelForm. `image_processors` : nom du champ -> fonction(envoi) qui valide et ré-encode (ValidationError sinon).

    Pour chaque champ, le formulaire accepte aussi `remove_<champ>` (retire l'image existante). Sur une modification,
    l'ancien fichier est supprimé une fois l'image remplacée ou retirée (après validation de la transaction).
    Un champ retiré du formulaire (droits insuffisants) est ignoré, `remove_<champ>` compris.
    """
    image_processors = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._previous_images = {}
        for name in self.image_processors:
            if name not in self.fields:
                continue
            self.fields[name].widget = forms.FileInput(attrs={'accept': ACCEPTED_TYPES})
            self.fields[name].required = False
            self.fields[f'remove_{name}'] = forms.BooleanField(required=False)
            setattr(self, f'clean_{name}', partial(self._clean_image, name))
            current = getattr(self.instance, name)
            if self.instance.pk and current:
                self._previous_images[name] = (current.storage, current.name)

    def drop_image_field(self, name):
        self.fields.pop(name, None)
        self.fields.pop(f'remove_{name}', None)
        self._previous_images.pop(name, None)

    def uploaded_image(self, name):
        return self.files.get(self.add_prefix(name))

    def _clean_image(self, name):
        upload = self.uploaded_image(name)
        if upload:
            return self.image_processors[name](upload)
        # False : le champ fichier de Django vide l'image existante
        return False if self[f'remove_{name}'].data else self.cleaned_data[name]

    def delete_replaced_images(self):
        """À appeler une fois l'instance enregistrée."""
        for name, (storage, previous) in self._previous_images.items():
            if name in self.fields and (self.uploaded_image(name) or self[f'remove_{name}'].data):
                transaction.on_commit(lambda storage=storage, previous=previous: delete_stored_file(storage, previous))

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            self.delete_replaced_images()
        return instance
