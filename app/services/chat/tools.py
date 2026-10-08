"""Ce que le modèle a le droit d'appeler. Un outil = une déclaration pour Gemini + une exécution côté serveur.

Le modèle ne fournit jamais de coordonnées : la position vient de l'appareil du membre (ou d'un nom de lieu géocodé ici), elle ne
quitte donc jamais le serveur vers Google. Chaque argument est revalidé : la sortie d'un modèle est une entrée non fiable.
"""
from abc import ABC, abstractmethod

from google.genai import types

from . import geocoding, places
from .geo import Coordinates
from .sanitize import clean_text

KINDS = ('bar', 'brewery', 'any')
NEEDS_LOCATION_KEY = 'needs_location'  # présent dans le résultat d'un outil qui n'a pas pu travailler faute de position


class Tool(ABC):
    name: str
    description: str

    @abstractmethod
    def parameters(self) -> types.Schema: ...

    @abstractmethod
    def run(self, args: dict) -> dict:
        """Résultat sérialisable en JSON, renvoyé au modèle comme donnée."""

    def declaration(self):
        return types.FunctionDeclaration(name=self.name, description=self.description, parameters=self.parameters())


class FindPlacesTool(Tool):
    name = 'find_places'
    description = (
        "Trouve des bars, pubs ou brasseries proches du membre (ou d'une ville nommée), classés par pertinence puis distance. "
        "À utiliser pour toute question sur où boire une bière, une marque ou un style."
    )

    def __init__(self, origin: Coordinates | None):
        self.origin = origin

    def parameters(self):
        text, number = types.Type.STRING, types.Type.NUMBER
        return types.Schema(type=types.Type.OBJECT, properties={
            'keyword': types.Schema(type=text, description="Bière, marque ou style recherché (ex. « guinness », « IPA »). Vide si aucun."),
            'kind': types.Schema(type=text, enum=list(KINDS), description="bar (bars et pubs), brewery (brasseries) ou any."),
            'place_name': types.Schema(type=text, description="Ville ou quartier, seulement si le membre en cite un."),
            'radius_km': types.Schema(type=number, description=f"Rayon de recherche en km (1 à {places.MAX_RADIUS_KM}, {places.DEFAULT_RADIUS_KM} par défaut)."),
        })

    def run(self, args):
        kind = args.get('kind') if args.get('kind') in KINDS else 'any'
        place_name = clean_text(args.get('place_name'), geocoding.MAX_QUERY_LENGTH)
        origin = geocoding.geocode(place_name) if place_name else self.origin
        if origin is None and place_name:
            return {'error': "Lieu introuvable : demande au membre de préciser la ville."}
        if origin is None:
            return {
                'error': "Position inconnue : demande au membre d'activer le bouton de localisation du chat ou de citer une ville.",
                NEEDS_LOCATION_KEY: True,
            }
        keyword = places.clean_keyword(args.get('keyword'))
        result = places.find_nearby(origin, kind, keyword, self._radius(args.get('radius_km')))
        return {
            'searched_around': place_name or 'la position du membre',
            'keyword': keyword,
            'complete': result.complete,
            'places': [{
                'name': place.name, 'type': place.kind, 'distance_km': round(place.distance_km, 1), 'address': place.address,
                'link': place.link, 'confirmed_match': place.keyword_match, 'verified_on_pokebeer': place.verified,
            } for place in result.places],
        }

    @staticmethod
    def _radius(raw):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return places.DEFAULT_RADIUS_KM


def build_tools(origin):
    """Outils disponibles pour cette conversation, par nom."""
    return {tool.name: tool for tool in (FindPlacesTool(origin),)}
