"""Brasseries et bars."""

from django.db import models

from ..validators import MAX_TEXT_LENGTH, plain_text_validator
from ..fields import PublicSlugField
from ..domain.upload_paths import bar_image_path, brewery_image_path

from django.contrib.postgres.indexes import GinIndex

from ..domain import match_keys
from .mixins import GeocodableMixin, MatchKeyMixin, OfficialImageMixin, PostalAddressMixin, VerifiableMixin


class Establishment(OfficialImageMixin, PostalAddressMixin, GeocodableMixin, VerifiableMixin, MatchKeyMixin):
    """Ce que brasseries et bars ont en commun : nom, adresse, SIRET, contacts et position sur la carte.

    Ce qui diffère reste dans chaque modèle : l'image (dossier de stockage), les gérants (nom de la relation inverse), la description
    et les dates de suivi."""

    name = models.CharField(max_length=150, blank=False, verbose_name="Nom", validators=[plain_text_validator])
    slug = PublicSlugField(source='name')
    siret = models.CharField(max_length=14, unique=True, blank=True, null=True, verbose_name="Numéro SIRET")

    # Contact
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Téléphone")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    website = models.URLField(blank=True, null=True, verbose_name="Site web")
    instagram = models.URLField(blank=True, null=True, verbose_name="Instagram")
    facebook = models.URLField(blank=True, null=True, verbose_name="Facebook")

    # Géolocalisation
    latitude = models.FloatField(blank=True, null=True, verbose_name="Latitude")
    longitude = models.FloatField(blank=True, null=True, verbose_name="Longitude")

    class Meta:
        abstract = True
        ordering = ['name']

    def __str__(self):
        return self.name


class Brewery(Establishment):
    MATCH_KIND = match_keys.BREWERY

    description = models.TextField(max_length=MAX_TEXT_LENGTH, verbose_name="Description")
    image = models.ImageField(upload_to=brewery_image_path, blank=True, null=True, verbose_name="Image")
    managers = models.ManyToManyField('BeerUser', blank=True, related_name='managed_breweries', verbose_name="Gérants")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, null=True, verbose_name="Date de création")
    updated_at = models.DateTimeField(auto_now=True, null=True, verbose_name="Dernière modification")

    class Meta(Establishment.Meta):
        verbose_name = "Brasserie"
        indexes = [GinIndex(fields=['match_key'], name='brewery_match_key_trgm', opclasses=['gin_trgm_ops'])]


class Bar(Establishment):
    MATCH_KIND = match_keys.BAR

    description = models.TextField(max_length=MAX_TEXT_LENGTH, blank=True, null=True, verbose_name="Description")
    image = models.ImageField(upload_to=bar_image_path, blank=True, null=True, verbose_name="Image")
    managers = models.ManyToManyField('BeerUser', blank=True, related_name='managed_bars', verbose_name="Gérants")

    # Traçabilité et Modération
    added_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='added_bars', verbose_name="Ajouté par")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de création")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Dernière modification")

    class Meta(Establishment.Meta):
        verbose_name = "Bar"
        verbose_name_plural = "Bars"
        indexes = [GinIndex(fields=['match_key'], name='bar_match_key_trgm', opclasses=['gin_trgm_ops'])]
