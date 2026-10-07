"""Brasseries et bars."""

from django.db import models

from ..validators import MAX_TEXT_LENGTH, plain_text_validator
from ..fields import PublicSlugField
from ..services.official_images import bar_image_path, brewery_image_path

from .mixins import GeocodableMixin, OfficialImageMixin, VerifiableMixin


class Brewery(OfficialImageMixin, GeocodableMixin, VerifiableMixin):
    name = models.CharField(max_length=150, blank=False, verbose_name="Nom", validators=[plain_text_validator])
    slug = PublicSlugField(source='name')
    description = models.TextField(max_length=MAX_TEXT_LENGTH, verbose_name="Description")
    image = models.ImageField(upload_to=brewery_image_path, blank=True, null=True, verbose_name="Image")
    siret = models.CharField(max_length=14, unique=True, blank=True, null=True, verbose_name="Numéro SIRET")
    managers = models.ManyToManyField('BeerUser', blank=True, related_name='managed_breweries', verbose_name="Gérants")
    
    # champs de contact
    address = models.CharField(max_length=255, blank=True, null=True, verbose_name="Adresse complète")
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Téléphone")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    website = models.URLField(blank=True, null=True, verbose_name="Site web")
    instagram = models.URLField(blank=True, null=True, verbose_name="Instagram")
    facebook = models.URLField(blank=True, null=True, verbose_name="Facebook")
    
    # Géolocalisation
    latitude = models.FloatField(blank=True, null=True, verbose_name="Latitude")
    longitude = models.FloatField(blank=True, null=True, verbose_name="Longitude")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, null=True, verbose_name="Date de création")
    updated_at = models.DateTimeField(auto_now=True, null=True, verbose_name="Dernière modification")
    
    class Meta:
        verbose_name = "Brasserie"
        ordering = ['name']

    def __str__(self):
        return self.name
    
class Bar(OfficialImageMixin, GeocodableMixin, VerifiableMixin):
    name = models.CharField(max_length=150, blank=False, verbose_name="Nom", validators=[plain_text_validator])
    slug = PublicSlugField(source='name')
    description = models.TextField(max_length=MAX_TEXT_LENGTH, blank=True, null=True, verbose_name="Description")
    image = models.ImageField(upload_to=bar_image_path, blank=True, null=True, verbose_name="Image")
    siret = models.CharField(max_length=14, unique=True, blank=True, null=True, verbose_name="Numéro SIRET")
    managers = models.ManyToManyField('BeerUser', blank=True, related_name='managed_bars', verbose_name="Gérants")
    
    # Localisation et Contact
    address = models.CharField(max_length=255, blank=True, null=True, verbose_name="Adresse complète")
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Téléphone")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    website = models.URLField(blank=True, null=True, verbose_name="Site web")
    instagram = models.URLField(blank=True, null=True, verbose_name="Instagram")
    facebook = models.URLField(blank=True, null=True, verbose_name="Facebook")
    
    # Géolocalisation
    latitude = models.FloatField(blank=True, null=True, verbose_name="Latitude")
    longitude = models.FloatField(blank=True, null=True, verbose_name="Longitude")
    
    # Traçabilité et Modération
    added_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='added_bars', verbose_name="Ajouté par")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de création")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Dernière modification")
    
    class Meta:
        verbose_name = "Bar"
        verbose_name_plural = "Bars"
        ordering = ['name']

    def __str__(self):
        return self.name
