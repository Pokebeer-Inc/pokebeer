"""Mise en page et vues personnalisées des statistiques de l'administration."""

from django.db import models


class AnalyticsLayout(models.Model):
    """Disposition personnelle d'une page d'analytics : ordre des tuiles et tuiles masquées (une ligne par membre et par page)."""
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='analytics_layouts')
    page_key = models.CharField(max_length=30)
    order = models.JSONField(default=list)
    hidden = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Disposition d'analytics"
        constraints = [models.UniqueConstraint(fields=['user', 'page_key'], name='unique_analytics_layout_per_page')]

class AnalyticsView(models.Model):
    """Vue d'analytics personnalisée : un ensemble de tuiles nommé, propre à un administrateur."""
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='analytics_views')
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Vue d'analytics"
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['user', 'name'], name='unique_analytics_view_name_per_user')]

    def __str__(self):
        return self.name


class AnalyticsTile(models.Model):
    """Tuile d'une vue personnalisée : titre et définition (jeu de données, regroupement, mesures, graphique)."""
    view = models.ForeignKey(AnalyticsView, on_delete=models.CASCADE, related_name='tiles')
    title = models.CharField(max_length=100)
    spec = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tuile d'analytics"
        ordering = ['pk']

    def __str__(self):
        return self.title
