"""Ce qui distingue une brasserie d'un bar ; tout le reste (édition, équipe, carte admin) est partagé."""
from dataclasses import dataclass

from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from ..forms import BarEditForm, BreweryEditForm
from ..models import Bar, Brewery


@dataclass(frozen=True)
class PlaceKind:
    key: str  # 'brewery' | 'bar' : nom du champ FK de Notification et préfixe des URLs
    model: type
    edit_form: type
    noun: str  # « la brasserie » / « le bar »
    label: str  # « Brasserie » / « Bar »

    @property
    def detail_url(self):
        return f'{self.key}_detail'

    def detail_kwargs(self, place):
        return {f'{self.key}_slug': place.slug}

    def detail_path(self, place):
        """Chemin de la page publique (relatif : jamais un hôte construit à partir de données)."""
        return reverse(self.detail_url, kwargs=self.detail_kwargs(place))

    def redirect_to_detail(self, place):
        return redirect(self.detail_url, **self.detail_kwargs(place))

    def get(self, slug):
        return get_object_or_404(self.model, slug=slug)


BREWERY = PlaceKind('brewery', Brewery, BreweryEditForm, 'la brasserie', 'Brasserie')
BAR = PlaceKind('bar', Bar, BarEditForm, 'le bar', 'Bar')
PLACE_KINDS = (BREWERY, BAR)
