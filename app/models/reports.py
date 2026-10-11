"""Signalements de contenus et de membres."""

from django.db import models

from ..fields import PublicSlugField


class Report(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Envoyé'),
        ('review', 'En cours d\'examen'),
        ('resolved', 'Traité'),
    ]
    REASON_CHOICES = [
        ('spam', 'Spam ou publicité'),
        ('offensive', 'Contenu offensant / haineux'),
        ('fake', 'Fausse information / Faux profil'),
        ('other', 'Autre raison'),
    ]
    
    reporter = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='submitted_reports', verbose_name="Signalé par")
    slug = PublicSlugField()
    
    # Cibles possibles (une seule sera remplie par signalement)
    reported_beer = models.ForeignKey('Beer', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Bière signalée")
    reported_drink = models.ForeignKey('Drinks', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Dégustation signalée")
    reported_user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, null=True, blank=True, related_name='reports_received', verbose_name="Membre signalé")
    reported_brewery = models.ForeignKey('Brewery', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Brasserie signalée")

    reason = models.CharField(max_length=20, choices=REASON_CHOICES, verbose_name="Raison")
    description = models.TextField(max_length=1000, verbose_name="Description détaillée")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Statut")
    admin_response = models.TextField(blank=True, null=True, verbose_name="Décision de l'administrateur")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date")

    class Meta:
        verbose_name = "Signalement"
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status'], name='report_status_idx')]  # compteur « à traiter » de l'administration
        constraints = [
            # Un signalement vise exactement une cible
            models.CheckConstraint(
                condition=(
                    models.Q(reported_beer__isnull=False, reported_drink__isnull=True, reported_user__isnull=True, reported_brewery__isnull=True)
                    | models.Q(reported_beer__isnull=True, reported_drink__isnull=False, reported_user__isnull=True, reported_brewery__isnull=True)
                    | models.Q(reported_beer__isnull=True, reported_drink__isnull=True, reported_user__isnull=False, reported_brewery__isnull=True)
                    | models.Q(reported_beer__isnull=True, reported_drink__isnull=True, reported_user__isnull=True, reported_brewery__isnull=False)
                ),
                name='report_exactly_one_target',
                violation_error_message="Choisissez exactement une cible : bière, note, membre ou brasserie.",
            ),
        ]

    def __str__(self):
        return f"Signalement #{self.id} par {self.reporter.username} - {self.get_status_display()}"
