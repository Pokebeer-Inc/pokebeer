"""Formulaires de création/édition d'une vue et d'une tuile : la validation métier est celle de `spec.validate`."""
from django import forms

from .catalog import CATALOG
from .spec import CHART_TYPES, DEFAULT_LIMIT, MAX_LIMIT, SORTS, SpecError, TITLE_MAX, clean_title, validate
from .service import NAME_MAX, clean_name


def _union(attribute):
    """Choix de tous les jeux de données (le JS affine selon le jeu choisi ; le serveur revalide toujours)."""
    choices = {}
    for dataset in CATALOG.values():
        for key, item in getattr(dataset, attribute).items():
            choices.setdefault(key, item.label)
    return list(choices.items())


class ViewNameForm(forms.Form):
    name = forms.CharField(max_length=NAME_MAX, label="Nom de la vue")

    def clean_name(self):
        try:
            return clean_name(self.cleaned_data['name'])
        except SpecError as error:
            raise forms.ValidationError(str(error)) from None


class TileForm(forms.Form):
    title = forms.CharField(max_length=TITLE_MAX, label="Titre de la tuile")
    dataset = forms.ChoiceField(choices=[(key, dataset.label) for key, dataset in CATALOG.items()], label="Données")
    dimension = forms.ChoiceField(choices=[('', '— Aucun (valeur unique) —'), *_union('dimensions')], required=False, label="Regrouper par")
    measures = forms.MultipleChoiceField(choices=_union('measures'), label="Afficher")
    chart = forms.ChoiceField(choices=list(CHART_TYPES.items()), label="Type de graphique")
    limit = forms.IntegerField(min_value=1, max_value=MAX_LIMIT, required=False, initial=DEFAULT_LIMIT, label="Nombre de lignes maximum")
    sort = forms.ChoiceField(choices=list(SORTS.items()), required=False, label="Tri")
    trend = forms.BooleanField(required=False, label="Ajouter moyenne mobile et prévision")

    def clean_title(self):
        try:
            return clean_title(self.cleaned_data['title'])
        except SpecError as error:
            raise forms.ValidationError(str(error)) from None

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        try:
            cleaned['spec'] = validate({key: cleaned.get(key) for key in ('dataset', 'dimension', 'measures', 'chart', 'limit', 'sort', 'trend')})
        except SpecError as error:
            raise forms.ValidationError(str(error)) from None
        return cleaned

    @classmethod
    def from_tile(cls, tile):
        return cls(initial={'title': tile.title, **tile.spec})
