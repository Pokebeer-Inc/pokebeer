"""Données de la carte admin : toutes les brasseries et tous les bars géolocalisés, sous une forme unique."""
from django.db.models import Count

from .places import PLACE_KINDS

# Seuls les champs déjà publics sur la page de l'établissement : ni SIRET, ni identité des gérants
PUBLIC_FIELDS = ('slug', 'name', 'description', 'address', 'phone', 'email', 'website', 'instagram', 'facebook',
                 'latitude', 'longitude', 'is_verified', 'verified_at')


def places_for_map():
    places = []
    for kind in PLACE_KINDS:
        queryset = (
            kind.model.objects
            .filter(latitude__isnull=False, longitude__isnull=False)
            .annotate(managers_count=Count('managers'))
            .only(*PUBLIC_FIELDS)
        )
        for place in queryset:
            places.append({
                'type': kind.key,
                'type_label': kind.label,
                'url': kind.detail_path(place),
                'managers_count': place.managers_count,
                **{field: getattr(place, field) for field in PUBLIC_FIELDS if field != 'verified_at'},
                'verified_at': place.verified_at.date().isoformat() if place.verified_at else None,
            })
    return places
