"""Référentiel des styles de bière (voir services/catalog/style_registry.py)."""
from django.db import models

from ..validators import plain_text_validator


class Style(models.Model):
    """Style officiel : un nom, une famille de styles comparables et les écritures qui y mènent (« ipa », « India Pale Ale » -> « IPA »)."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Nom officiel", validators=[plain_text_validator])
    family = models.CharField(max_length=60, verbose_name="Famille", help_text="Regroupe des styles comparables dans les statistiques.")
    aliases = models.TextField(blank=True, default='', verbose_name="Alias", help_text="Un par ligne : autres écritures ramenées à ce style.")

    class Meta:
        verbose_name = "Style de bière"
        verbose_name_plural = "Styles de bière"
        ordering = ['family', 'name']

    def __str__(self):
        return self.name

    @property
    def alias_list(self):
        return [line.strip() for line in self.aliases.splitlines() if line.strip()]
