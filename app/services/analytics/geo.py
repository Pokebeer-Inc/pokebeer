"""Géométrie : distances et regroupement en cases. Pas de géocodage inverse (aucun appel réseau)."""
from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000
CELL_SIZE_DEG = 0.1  # ~11 km : assez large pour ne jamais désigner une adresse


def haversine_m(lat1, lon1, lat2, lon2):
    d_lat, d_lon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def cell_of(lat, lon):
    """Case de la grille contenant le point (coordonnées du coin sud-ouest, arrondies)."""
    return (round(lat // CELL_SIZE_DEG * CELL_SIZE_DEG, 1), round(lon // CELL_SIZE_DEG * CELL_SIZE_DEG, 1))


def cell_center(cell):
    return cell[0] + CELL_SIZE_DEG / 2, cell[1] + CELL_SIZE_DEG / 2


def within_m(point, places, radius_m):
    """Établissements (lat, lon, …) situés à moins de radius_m du point ; pré-filtre par boîte englobante."""
    lat, lon = point
    margin = radius_m / 111_000 * 1.5
    return [
        place for place in places
        if abs(place[0] - lat) <= margin and abs(place[1] - lon) <= margin * 2
        and haversine_m(lat, lon, place[0], place[1]) <= radius_m
    ]
