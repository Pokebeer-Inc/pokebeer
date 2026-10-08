"""Ce qui distingue une brasserie d'un bar ; tout le reste (édition, équipe, carte admin) est partagé."""
from dataclasses import dataclass
from urllib.parse import urlencode

from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from ..forms import BarEditForm, BarProForm, BreweryEditForm, BreweryProForm
from ..models import Bar, Brewery


@dataclass(frozen=True)
class PlaceKind:
    key: str  # 'brewery' | 'bar' : nom du champ FK de Notification et préfixe des URLs
    model: type
    edit_form: type
    pro_form: type  # fiche saisie à l'inscription d'un gérant
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

    def has_coordinates(self, place):
        return place.latitude is not None and place.longitude is not None

    def map_path(self, place):
        """Chemin de la carte centrée sur l'établissement (relatif) : la carte ouvre sa fiche au clic sur son marqueur."""
        return f"{reverse('map')}?{urlencode({'kind': self.key, 'place': place.slug})}"

    def target_path(self, place):
        """Où mène un résultat de recherche : la carte si l'établissement est localisé, sinon sa fiche."""
        return self.map_path(place) if self.has_coordinates(place) else self.detail_path(place)

    def public(self, place):
        """Données déjà publiques de la fiche, sans SIRET ni gérants (liste « Près de moi » calculée sur l'appareil)."""
        return {
            'kind': self.key, 'kind_label': self.label, 'name': place.name, 'slug': place.slug, 'address': place.address or '',
            'image': place.image_url, 'lat': place.latitude, 'lng': place.longitude, 'verified': place.is_verified,
            'url': self.map_path(place),
        }

    def redirect_to_detail(self, place):
        return redirect(self.detail_url, **self.detail_kwargs(place))

    def get(self, slug):
        return get_object_or_404(self.model, slug=slug)


BREWERY = PlaceKind('brewery', Brewery, BreweryEditForm, BreweryProForm, 'la brasserie', 'Brasserie')
BAR = PlaceKind('bar', Bar, BarEditForm, BarProForm, 'le bar', 'Bar')
PLACE_KINDS = (BREWERY, BAR)
PLACE_KINDS_BY_KEY = {kind.key: kind for kind in PLACE_KINDS}


def kind_of(place):
    """Type (PlaceKind) d'une fiche : brasserie ou bar."""
    return next(kind for kind in PLACE_KINDS if isinstance(place, kind.model))


def with_targets(places, kind):
    """Liste des établissements, chacun portant `target_url` (carte ou fiche) pour les gabarits de résultats."""
    places = list(places)
    for place in places:
        place.target_url = kind.target_path(place)
    return places
