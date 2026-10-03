"""Certification (coche « vérifié ») d'un bar, d'une brasserie ou d'une bière : règle unique partagée par l'admin."""
from django.utils import timezone

from ..models import VerifiableMixin

VERIFICATION_FIELDS = ["is_verified", "verified_by", "verified_at"]


def certify(obj, user):
    """Pose la coche « vérifié » ; seuls ces trois champs sont écrits (aucune autre modification n'est enregistrée)."""
    if not isinstance(obj, VerifiableMixin):
        raise TypeError(f"{type(obj).__name__} ne peut pas être certifié.")
    obj.is_verified = True
    obj.verified_by = user
    obj.verified_at = timezone.now()
    obj.save(update_fields=VERIFICATION_FIELDS)
