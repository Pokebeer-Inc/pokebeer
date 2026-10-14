"""Formulaire d'édition des champs publics d'une fiche (bière, brasserie, bar), partagé par les suggestions des membres et par les retouches
de l'équipe lors de la validation. Les champs éditables sont déclarés par type de contenu (ModeratedContent.suggest_fields).
"""
from functools import cache

from django import forms
from django.forms import modelform_factory

from app.services.catalog.beer_fields import clean_multiline

from .content import CONTENT_TYPES

LONG_TEXT = ('description',)
MAX_VALUE_LENGTH = 2000


@cache
def _form_class(kind):
    content = CONTENT_TYPES[kind]
    return modelform_factory(content.model, fields=list(content.suggest_fields), widgets={
        name: forms.Textarea(attrs={'rows': 4}) for name in LONG_TEXT if name in content.suggest_fields
    })


def edit_form(content, *, instance, data=None, initial=None, css='pb-input', auto_id='suggest_%s'):
    """Formulaire des champs suggérables d'une fiche (ModelForm : mêmes règles de validation que partout)."""
    form = _form_class(content.kind)(data, instance=instance, initial=initial, auto_id=auto_id)
    for field in form.fields.values():
        field.widget.attrs['class'] = css
    return form


def plain_values(content, data):
    """Valeurs reçues réduites à du texte brut (sans balise, caractère invisible ni emoji) : jamais de HTML dans une fiche publique."""
    return {name: clean_multiline(data.get(name), MAX_VALUE_LENGTH) for name in content.suggest_fields if name in data}


def problems(content, form, target):
    """Messages d'erreur du formulaire du modèle et des règles du type de contenu (liste vide si la suggestion est valide)."""
    if not form.is_valid():
        return [f"{form.fields[name].label or name} : {' '.join(errors)}" for name, errors in form.errors.items() if name in form.fields]
    return content.suggestion_errors(target, form.cleaned_data)


