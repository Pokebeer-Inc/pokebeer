"""Mesures d'usage minimales : vues des fiches, jours d'activité, recherches sans résultat.

Principe commun : on stocke le moins possible et on purge vite (services/tracking). Aucune de ces lignes ne dit « qui a regardé quoi » :
- PageView ne contient que des compteurs par fiche et par jour ;
- PageViewVisitor ne sert qu'à ne compter un visiteur qu'une fois par jour ; empreinte non réversible sans la clé du site, supprimée le lendemain ;
- ActivityDay dit qu'un membre est venu tel jour (sans rien dire de ce qu'il a fait) et disparaît avec le compte ;
- CatalogMiss compte des termes recherchés sans résultat, sans aucun lien avec un membre.
"""
from django.db import models
from django.utils import timezone


class PageView(models.Model):
    """Vues d'une fiche (bière, brasserie ou bar) sur une journée : nombre de vues et de visiteurs distincts."""

    class Kind(models.TextChoices):
        BEER = 'beer', 'Bière'
        BREWERY = 'brewery', 'Brasserie'
        BAR = 'bar', 'Bar'

    kind = models.CharField(max_length=10, choices=Kind.choices)
    object_id = models.PositiveBigIntegerField()  # identifiant sans clé étrangère : les chiffres d'une fiche supprimée disparaissent par purge, pas par cascade
    day = models.DateField(default=timezone.localdate)
    views = models.PositiveIntegerField(default=0)
    visitors = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Vues d'une fiche"
        verbose_name_plural = "Vues des fiches"
        constraints = [models.UniqueConstraint(fields=['kind', 'object_id', 'day'], name='unique_page_view_per_day')]
        indexes = [models.Index(fields=['day'], name='pageview_day_idx')]  # analytics par période et purge

    def __str__(self):
        return f"{self.kind} {self.object_id} {self.day} : {self.views}"


class PageViewVisitor(models.Model):
    """Empreinte d'un visiteur pour une fiche et un jour : sert uniquement à ne pas le compter deux fois. Supprimée dès le lendemain."""
    kind = models.CharField(max_length=10, choices=PageView.Kind.choices)
    object_id = models.PositiveBigIntegerField()
    day = models.DateField(default=timezone.localdate)
    digest = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['kind', 'object_id', 'day', 'digest'], name='unique_page_view_visitor')]
        indexes = [models.Index(fields=['day'], name='pageviewvisitor_day_idx')]  # purge quotidienne

    def __str__(self):
        return f"{self.kind} {self.object_id} {self.day}"


class ActivityDay(models.Model):
    """Un jour où le membre est venu sur le site : base des actifs quotidiens, hebdomadaires et mensuels et de la rétention."""
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='activity_days')
    day = models.DateField(default=timezone.localdate)

    class Meta:
        verbose_name = "Jour d'activité"
        verbose_name_plural = "Jours d'activité"
        constraints = [models.UniqueConstraint(fields=['user', 'day'], name='unique_activity_day')]
        indexes = [models.Index(fields=['day'], name='activityday_day_idx')]  # actifs par période et purge

    def __str__(self):
        return f"{self.user_id} {self.day}"


class CatalogMiss(models.Model):
    """Demande sans résultat : terme recherché sans réponse, code-barres inconnu, étiquette non reconnue. Compteur journalier, sans membre."""

    class Source(models.TextChoices):
        BEER_SEARCH = 'beer_search', 'Recherche de bière'
        BREWERY_SEARCH = 'brewery_search', 'Recherche de brasserie'
        BAR_SEARCH = 'bar_search', 'Recherche de bar'
        EAN = 'ean', 'Code-barres inconnu'
        LABEL = 'label', 'Étiquette non reconnue'

    source = models.CharField(max_length=20, choices=Source.choices)
    key = models.CharField(max_length=60, blank=True, default='')  # terme normalisé ou code-barres ; vide pour une étiquette
    day = models.DateField(default=timezone.localdate)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Demande sans résultat"
        verbose_name_plural = "Demandes sans résultat"
        constraints = [models.UniqueConstraint(fields=['source', 'key', 'day'], name='unique_catalog_miss_per_day')]
        indexes = [models.Index(fields=['day'], name='catalogmiss_day_idx')]

    def __str__(self):
        return f"{self.source} {self.key!r} {self.day} : {self.count}"
