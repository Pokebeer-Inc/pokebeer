"""Briques communes aux modèles : géocodage automatique, coche « vérifié », image officielle, clés de comparaison des noms."""

from django.db import models

from ..services.establishments import address as address_service
from ..services.catalog import match_keys


class PostalAddressMixin(models.Model):
    """Adresse découpée : rue (à compléter plus tard par le gérant ou l'admin), code postal et ville (déduite du code postal, voir
    services/establishments/postal_codes.py). `address` reste disponible en lecture et en écriture sous forme de texte complet."""
    street = models.CharField(max_length=255, blank=True, default='', verbose_name="Adresse (numéro et rue)")
    postal_code = models.CharField(max_length=10, blank=True, default='', db_index=True, verbose_name="Code postal")
    city = models.CharField(max_length=100, blank=True, default='', verbose_name="Ville")

    class Meta:
        abstract = True

    @property
    def address(self):
        return address_service.compose(self.street, self.postal_code, self.city)

    @address.setter
    def address(self, value):
        self.street, self.postal_code, self.city = address_service.parse(value)


class GeocodableMixin(models.Model):
    """
    Classe abstraite pour les modèles à adresse ('street', 'postal_code', 'city') et à coordonnées ('latitude', 'longitude').

    Elle se contente de savoir si l'adresse a changé (sans requête supplémentaire quand la fiche vient de la base) : le calcul des
    coordonnées est fait par `services/establishments/place_geocoding.py` (signal pre_save), le modèle n'appelle aucun service extérieur.
    """
    class Meta:
        abstract = True

    @classmethod
    def from_db(cls, db, field_names, values):
        """Retient l'adresse telle qu'elle est en base : savoir si elle a changé ne coûte alors aucune requête."""
        instance = super().from_db(db, field_names, values)
        loaded = instance.__dict__
        # Champs différés (`only()`/`defer()`) : on ne les lit pas ici, `address_changed` ira alors chercher l'ancienne adresse
        instance._loaded_address = instance.address if all(name in loaded for name in ('street', 'postal_code', 'city')) else None
        return instance

    def address_changed(self):
        """Vrai pour une nouvelle fiche, ou quand l'adresse enregistrée n'est plus celle de l'instance."""
        if not self.pk or self._state.adding:
            return True
        loaded = getattr(self, '_loaded_address', None)
        if loaded is None:
            stored = type(self).objects.filter(pk=self.pk).first()
            loaded = stored.address if stored else None
        return loaded != self.address

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._loaded_address = self.address

class VerifiableMixin(models.Model):
    """Coche « vérifié » posée par un admin (voir services/establishments/verification.py) ; jamais modifiable par un formulaire public."""
    is_verified = models.BooleanField(default=False, verbose_name="Vérifié")
    verified_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_%(class)s_set', verbose_name="Vérifié par")
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de vérification")

    class Meta:
        abstract = True

class MatchKeyMixin(models.Model):
    """Clés de comparaison du nom (voir services/catalog/match_keys.py), recalculées à chaque enregistrement : la détection de doublons
    les interroge avec un index au lieu de relire tous les noms. À hériter sur un modèle qui a un champ `name`, avec MATCH_KIND."""
    MATCH_KIND = None  # match_keys.BEER ou match_keys.BREWERY

    name_key = models.CharField(max_length=match_keys.KEY_LENGTH, blank=True, default='', editable=False, db_index=True)
    match_key = models.CharField(max_length=match_keys.KEY_LENGTH, blank=True, default='', editable=False)

    class Meta:
        abstract = True

    def refresh_match_keys(self):
        self.name_key = match_keys.strict_key(self.name, self.MATCH_KIND)
        self.match_key = match_keys.loose_key(self.name, self.MATCH_KIND)

    def save(self, *args, **kwargs):
        self.refresh_match_keys()
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'name' in update_fields:
            kwargs['update_fields'] = {*update_fields, 'name_key', 'match_key'}
        super().save(*args, **kwargs)


class OfficialImageMixin:
    """Image officielle d'un établissement ou d'une bière (champ `image`)."""

    @property
    def image_url(self):
        """URL de l'image, ou None : à utiliser dans les gabarits (image.url lève une erreur sans fichier)."""
        return self.image.url if self.image else None
