"""Tirage du jour : cinq bières à découvrir, un tirage par membre et par jour."""

from django.db import models
from django.utils import timezone

from ..domain import rarity


class DailyDraw(models.Model):
    """Le tirage d'un membre pour un jour. Enregistré à l'ouverture : recharger la page ou revenir plus tard montre les mêmes cartes,
    jamais un nouveau tirage."""
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='daily_draws')
    day = models.DateField(default=timezone.localdate)
    revealed = models.PositiveSmallIntegerField(default=0, editable=False, verbose_name="Cartes révélées")  # progression : on reprend à la première carte non révélée
    completed_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Terminé le")  # toutes les cartes ont été révélées
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tirage du jour"
        verbose_name_plural = "Tirages du jour"
        constraints = [models.UniqueConstraint(fields=['user', 'day'], name='unique_daily_draw_per_day')]  # garantit « un par jour » même en cas de double clic
        indexes = [models.Index(fields=['day'], name='dailydraw_day_idx')]  # rappel quotidien

    def __str__(self):
        return f"{self.user_id} {self.day}"


class DailyDrawCard(models.Model):
    """Une bière du tirage, avec la rareté qu'elle avait au moment du tirage (la rareté évolue avec les dégustations, la carte reste)."""
    draw = models.ForeignKey(DailyDraw, on_delete=models.CASCADE, related_name='cards')
    beer = models.ForeignKey('Beer', on_delete=models.CASCADE, related_name='+')
    rarity = models.CharField(max_length=10, choices=rarity.CHOICES)
    position = models.PositiveSmallIntegerField()  # ordre de révélation

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(fields=['draw', 'position'], name='unique_draw_card_position'),
            models.UniqueConstraint(fields=['draw', 'beer'], name='unique_draw_card_beer'),
        ]

    def __str__(self):
        return f"{self.draw_id} #{self.position} {self.rarity}"
