"""Demandes de revendication d'un établissement (brasserie ou bar) par un gérant : examinées par l'équipe avant tout droit de gestion."""

from django.db import models
from django.utils import timezone


class EstablishmentClaim(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', "En attente"
        APPROVED = 'approved', "Acceptée"
        REJECTED = 'rejected', "Refusée"
        CANCELLED = 'cancelled', "Annulée par le demandeur"

    # Exactement l'un des deux (contrainte ci-dessous) : la fiche revendiquée
    brewery = models.ForeignKey('Brewery', on_delete=models.CASCADE, null=True, blank=True, related_name='claims')
    bar = models.ForeignKey('Bar', on_delete=models.CASCADE, null=True, blank=True, related_name='claims')
    claimant = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='claims', verbose_name="Demandeur")
    siret = models.CharField(max_length=14, verbose_name="SIRET déclaré")
    message = models.CharField(max_length=500, blank=True, verbose_name="Message à l'équipe")
    # Résultat du contrôle automatique du SIRET au moment de la demande (annuaire des entreprises) : sert de base à la décision
    registry = models.JSONField(default=dict, blank=True, verbose_name="Contrôle du SIRET")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name="Décidée par")
    reason = models.CharField(max_length=300, blank=True, verbose_name="Motif du refus")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Revendication d'établissement"
        verbose_name_plural = "Revendications d'établissement"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(brewery__isnull=False, bar__isnull=True) | models.Q(brewery__isnull=True, bar__isnull=False),
                name='claim_exactly_one_place',
            ),
            # Une seule demande en attente par membre et par fiche
            models.UniqueConstraint(fields=['claimant', 'brewery'], condition=models.Q(status='pending', brewery__isnull=False), name='one_pending_claim_per_brewery'),
            models.UniqueConstraint(fields=['claimant', 'bar'], condition=models.Q(status='pending', bar__isnull=False), name='one_pending_claim_per_bar'),
        ]

    def __str__(self):
        return f"{self.claimant.username} -> {self.place.name}"

    @property
    def place(self):
        return self.brewery or self.bar

    @property
    def kind_key(self):
        return 'brewery' if self.brewery_id else 'bar'

    @property
    def is_pending(self):
        return self.status == self.Status.PENDING
