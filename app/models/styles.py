"""Référentiel des styles de bière (voir services/catalog/style_registry.py) : familles, styles officiels ou à valider, et lien avec les bières."""
from django.core.exceptions import ValidationError
from django.db import models

from ..validators import plain_text_validator


class StyleFamily(models.Model):
    """Famille de styles comparables (« IPA », « Brune, porter et stout ») : ce qui rend les statistiques lisibles quand les styles sont nombreux."""
    name = models.CharField(max_length=60, unique=True, verbose_name="Nom", validators=[plain_text_validator])
    position = models.PositiveSmallIntegerField(default=0, verbose_name="Ordre d'affichage")

    class Meta:
        verbose_name = "Famille de styles"
        verbose_name_plural = "Familles de styles"
        ordering = ['position', 'name']

    def __str__(self):
        return self.name


class Style(models.Model):
    """Style de bière : un nom, une famille de styles comparables et les écritures qui y mènent (« ipa », « India Pale Ale » -> « IPA »).

    Un style officiel est géré par l'équipe. Un style saisi par un membre et absent du référentiel est gardé tel quel, « à valider » (`is_official`
    faux, sans famille) : l'équipe le rattache à une famille, ou en fait un alias d'un style officiel."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Nom officiel", validators=[plain_text_validator])
    family = models.ForeignKey(StyleFamily, on_delete=models.PROTECT, null=True, blank=True, related_name='styles', verbose_name="Famille",
                               help_text="Regroupe des styles comparables dans les statistiques. Vide : style à valider.")
    aliases = models.TextField(blank=True, default='', verbose_name="Alias", help_text="Un par ligne : autres écritures ramenées à ce style.")
    is_official = models.BooleanField(default=True, verbose_name="Officiel", help_text="Décoché : saisi par un membre, en attente de validation.")

    class Meta:
        verbose_name = "Style de bière"
        verbose_name_plural = "Styles de bière"
        ordering = ['family', 'name']
        constraints = [
            # Un style officiel est toujours rangé dans une famille : seuls les styles « à valider » (saisis par les membres) en sont dépourvus
            models.CheckConstraint(condition=models.Q(is_official=False) | models.Q(family__isnull=False), name='official_style_has_a_family'),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.is_official and not self.family_id:
            raise ValidationError({'family': "Un style officiel est rangé dans une famille."})

    @property
    def alias_list(self):
        return [line.strip() for line in self.aliases.splitlines() if line.strip()]


class BeerStyle(models.Model):
    """Un style d'une bière, à sa place dans la liste (« IPA, Stout » : IPA en position 0)."""
    beer = models.ForeignKey('Beer', on_delete=models.CASCADE, related_name='beer_styles')
    style = models.ForeignKey(Style, on_delete=models.PROTECT, related_name='beer_styles')
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position']
        constraints = [models.UniqueConstraint(fields=['beer', 'style'], name='unique_style_per_beer')]
        indexes = [models.Index(fields=['style', 'beer'], name='beerstyle_style_beer_idx')]  # « les bières de ce style »

    def __str__(self):
        return f"{self.beer_id} : {self.style_id} ({self.position})"
