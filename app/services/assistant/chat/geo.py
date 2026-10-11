"""Position du membre : validée, arrondie (~1 km) et jamais enregistrée. Calculs de distance pour classer les lieux."""
import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088
KM_PER_DEGREE = 111.32
COORDINATE_DECIMALS = 2  # 0,01° ≈ 1 km : assez pour « près de moi », trop peu pour reconnaître un domicile


@dataclass(frozen=True)
class Coordinates:
    lat: float
    lng: float

    @classmethod
    def parse(cls, raw):
        """Position arrondie, ou None si la donnée n'est pas une paire latitude/longitude valide."""
        if not isinstance(raw, dict):
            return None
        try:
            lat, lng = float(raw['lat']), float(raw['lng'])
        except (KeyError, TypeError, ValueError):
            return None
        if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
            return None
        return cls(round(lat, COORDINATE_DECIMALS), round(lng, COORDINATE_DECIMALS))

    def distance_km(self, lat, lng):
        """Distance à vol d'oiseau (haversine)."""
        d_lat, d_lng = math.radians(lat - self.lat), math.radians(lng - self.lng)
        a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(self.lat)) * math.cos(math.radians(lat)) * math.sin(d_lng / 2) ** 2
        return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))

    def bounding_box(self, radius_km):
        """(lat_min, lat_max, lng_min, lng_max) contenant le cercle de ce rayon : filtre rapide avant le calcul exact."""
        d_lat = radius_km / KM_PER_DEGREE
        d_lng = radius_km / (KM_PER_DEGREE * max(math.cos(math.radians(self.lat)), 0.01))
        return self.lat - d_lat, self.lat + d_lat, self.lng - d_lng, self.lng + d_lng
