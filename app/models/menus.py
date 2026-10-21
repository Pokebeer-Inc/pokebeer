"""Carte d'un bar : les bières qu'il sert, avec leur prix et leur format (voir services/establishments/menu.py)."""
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .beers import Drinks


class BarBeerQuerySet(models.QuerySet):
    def active(self):
        """Lignes en cours (pas retirées) dont la bière est toujours au catalogue."""
        return self.filter(removed_at__isnull=True, beer__is_deleted=False)


class BarBeer(models.Model):
    """Une bière servie par un bar. Une ligne retirée est conservée (`removed_at`) : l'historique de la carte reste analysable, et la bière
    peut revenir plus tard avec une nouvelle ligne."""
    bar = models.ForeignKey('Bar', on_delete=models.CASCADE, related_name='menu_entries')
    beer = models.ForeignKey('Beer', on_delete=models.CASCADE, related_name='bar_entries')
    price = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(999)],
                                verbose_name="Prix de vente (€)")
    serving_format = models.CharField(max_length=10, choices=Drinks.ServingFormat.choices, blank=True, default='', verbose_name="Format")
    added_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    added_at = models.DateTimeField(default=timezone.now)
    removed_at = models.DateTimeField(null=True, blank=True)

    objects = BarBeerQuerySet.as_manager()

    class Meta:
        verbose_name = "Bière à la carte"
        verbose_name_plural = "Bières à la carte"
        ordering = ['beer__name']
        constraints = [
            # Une seule ligne en cours par bière et par bar : deux ajouts simultanés (double clic) ne créent pas de doublon
            models.UniqueConstraint(fields=['bar', 'beer'], condition=models.Q(removed_at__isnull=True), name='one_active_menu_entry_per_beer'),
        ]
        indexes = [models.Index(fields=['bar', 'removed_at'], name='menu_bar_active_idx')]

    def __str__(self):
        return f"{self.bar_id} : {self.beer_id}"
