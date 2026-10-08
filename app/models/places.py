"""Lieux posés sur la carte par les membres et cache de géocodage inverse."""

from datetime import date
from django.db import models

from ..validators import MAX_TEXT_LENGTH
from ..fields import PublicSlugField


    
class BeerSpot(models.Model):
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='spots')
    slug = PublicSlugField()
    title = models.CharField(max_length=150, verbose_name="Titre du lieu")
    description = models.TextField(max_length=MAX_TEXT_LENGTH, blank=True, null=True, verbose_name="Description / Souvenirs")
    date = models.DateField(default=date.today, verbose_name="Date")
    latitude = models.FloatField()
    longitude = models.FloatField()
    
    drinks = models.ManyToManyField('Drinks', blank=True, related_name='spots', verbose_name="Dégustations associées")
    friends = models.ManyToManyField('BeerUser', blank=True, related_name='shared_spots', verbose_name="Amis associés")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Lieu de dégustation"
        ordering = ['-date']

    def __str__(self):
        return f"{self.title} - {self.user.username}"
    
class ReverseGeocode(models.Model):
    """Cache du géocodage inverse (OpenStreetMap/Nominatim) par position arrondie à ~11 m.

    Volontairement sans lien avec un membre ni un lieu : seule la position est mise en cache, ce qui évite
    de rappeler le service externe et de lui transmettre plus de coordonnées que nécessaire.
    """
    class PlaceKind(models.TextChoices):
        HOME = 'home', 'Domicile / habitation'
        BAR = 'bar', 'Bar, pub, restaurant'
        BREWERY = 'brewery', 'Brasserie'
        OUTDOOR = 'outdoor', 'Extérieur (parc, nature)'
        STREET = 'street', 'Voie publique'
        OTHER = 'other', 'Autre'

    lat_e4 = models.IntegerField(help_text="Latitude × 10 000, arrondie")
    lon_e4 = models.IntegerField(help_text="Longitude × 10 000, arrondie")
    place_kind = models.CharField(max_length=10, choices=PlaceKind.choices, blank=True)
    settlement = models.CharField(max_length=10, blank=True, help_text="city, town, village ou hamlet")
    is_urban = models.BooleanField(null=True, blank=True)
    city = models.CharField(max_length=150, blank=True)
    postcode = models.CharField(max_length=20, blank=True)
    department = models.CharField(max_length=150, blank=True)
    region = models.CharField(max_length=150, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    osm_category = models.CharField(max_length=50, blank=True)
    osm_type = models.CharField(max_length=50, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Géocodage inverse"
        constraints = [models.UniqueConstraint(fields=['lat_e4', 'lon_e4'], name='unique_reverse_geocode_position')]

    @property
    def is_resolved(self):
        return self.resolved_at is not None

    def __str__(self):
        return f"{self.lat_e4 / 10_000:.4f}, {self.lon_e4 / 10_000:.4f} - {self.city or '?'}"
