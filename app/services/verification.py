"""Certification (coche « vérifié ») d'un bar ou d'une brasserie : règle unique partagée par l'admin."""
from django.utils import timezone

VERIFICATION_FIELDS = ["is_verified", "verified_by", "verified_at"]


def certify_establishment(establishment, user):
    establishment.is_verified = True
    establishment.verified_by = user
    establishment.verified_at = timezone.now()
    establishment.save(update_fields=VERIFICATION_FIELDS)
