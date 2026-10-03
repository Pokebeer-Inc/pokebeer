"""Lieux des membres enrichis du géocodage inverse mis en cache (quand il existe) : base commune à la géographie,
aux bars et à la demande régionale. Aucune information nominative n'est conservée au-delà de l'identifiant de membre,
qui ne sert qu'à compter des membres distincts (k-anonymat)."""
from dataclasses import dataclass
from typing import Optional

from ...models import BeerSpot, ReverseGeocode
from .. import reverse_geocoding as rg
from . import geo
from .date import date_range


@dataclass(frozen=True)
class SpotPoint:
    spot_id: int
    user_id: int
    lat: float
    lon: float
    cell: tuple
    place_kind: str = ''          # vide tant que le lieu n'est pas géocodé
    is_urban: Optional[bool] = None
    city: str = ''
    department: str = ''
    region: str = ''

    @property
    def resolved(self):
        return bool(self.place_kind)

    @property
    def zone(self):
        """Libellé de zone : la ville si elle est connue, sinon la case de ~11 km."""
        if self.city:
            return f'{self.city} ({self.department})' if self.department else self.city
        return f'Zone {geo.cell_center(self.cell)[0]:.1f}, {geo.cell_center(self.cell)[1]:.1f}'


def spot_points(period):
    spots = date_range(BeerSpot.objects.all(), 'date', period.start).values_list('pk', 'user_id', 'latitude', 'longitude')
    cache = {(r.lat_e4, r.lon_e4): r for r in ReverseGeocode.objects.filter(resolved_at__isnull=False)}
    points = []
    for spot_id, user_id, lat, lon in spots:
        info = cache.get(rg.key_for(lat, lon))
        points.append(SpotPoint(
            spot_id, user_id, lat, lon, geo.cell_of(lat, lon),
            *( (info.place_kind, info.is_urban, info.city, info.department, info.region) if info else () ),
        ))
    return points
