"""Briques communes aux modèles : géocodage automatique, coche « vérifié », image officielle, clés de comparaison des noms."""

import requests
from django.db import models

from ..services import address as address_service, match_keys


# Le géocodage est synchrone dans la requête web : timeout court (connexion + lecture)
GEOCODING_TIMEOUT = 2

class PostalAddressMixin(models.Model):
    """Adresse découpée : rue (à compléter plus tard par le gérant ou l'admin), code postal et ville (déduite du code postal, voir
    services/postal_codes.py). `address` reste disponible en lecture et en écriture sous forme de texte complet."""
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
    Classe abstraite qui ajoute la logique de géocodage automatique.
    À hériter sur tout modèle possédant les champs 'address', 'latitude' et 'longitude'.
    """
    class Meta:
        abstract = True

    def _update_coordinates(self):
        """Appelle l'API OpenStreetMap pour convertir l'adresse en coordonnées. Sans rue, la fiche n'est pas placée : un point au centre de
        la ville laisserait croire à l'adresse de l'établissement."""
        if not self.street:
            self.latitude = None
            self.longitude = None
            return

        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': self.address,
            'format': 'json',
            'limit': 1
        }
        # L'API Nominatim exige un User-Agent personnalisé
        headers = {
            'User-Agent': 'PokebeerApp/1.0' 
        }

        try:
            response = requests.get(url, params=params, headers=headers, timeout=GEOCODING_TIMEOUT)
            data = response.json() if response.status_code == 200 else None
            if data:
                self.latitude = float(data[0]['lat'])
                self.longitude = float(data[0]['lon'])
                return
            if response.status_code != 200:
                print(f"Erreur de géocodage : HTTP {response.status_code}")
        except Exception as e:
            # En cas de coupure réseau ou erreur API, on ne fait pas crasher l'enregistrement
            print(f"Erreur de géocodage : {e}")
        # Adresse introuvable ou service indisponible : mieux vaut pas de carte que les coordonnées de l'ancienne adresse
        self.latitude = None
        self.longitude = None

    def save(self, *args, **kwargs):
        # On vérifie si c'est une modification d'un objet existant
        if self.pk:
            old_instance = type(self).objects.get(pk=self.pk)
            # On appelle l'API UNIQUEMENT si l'adresse a changé
            if old_instance.address != self.address:
                self._update_coordinates()
        else:
            # C'est une création de nouvel établissement
            self._update_coordinates()

        # On appelle le comportement de sauvegarde normal de Django
        super().save(*args, **kwargs)

class VerifiableMixin(models.Model):
    """Coche « vérifié » posée par un admin (voir services/verification.py) ; jamais modifiable par un formulaire public."""
    is_verified = models.BooleanField(default=False, verbose_name="Vérifié")
    verified_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_%(class)s_set', verbose_name="Vérifié par")
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de vérification")

    class Meta:
        abstract = True

class MatchKeyMixin(models.Model):
    """Clés de comparaison du nom (voir services/match_keys.py), recalculées à chaque enregistrement : la détection de doublons
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
