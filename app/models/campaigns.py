"""Campagnes e-mail de l'administration et leurs destinataires."""

from django.db import models
from django.utils import timezone


class EmailCampaign(models.Model):
    """Message rédigé dans l'administration et envoyé par lots à une audience (voir services/campaigns.py).

    Les destinataires sont figés au lancement (CampaignRecipient) : la suite de l'envoi ne dépend plus des critères.
    """

    class Kind(models.TextChoices):
        PROMOTIONAL = 'promotional', "Promotionnel (hors membres désinscrits)"
        SERVICE = 'service', "Alerte obligatoire (tous les membres actifs)"

    class Audience(models.TextChoices):
        ALL = 'all', "Tous les membres"
        ACTIVE = 'active', "Membres actifs"
        INACTIVE = 'inactive', "Membres inactifs"
        CUSTOM = 'custom', "Liste personnalisée"

    class Status(models.TextChoices):
        DRAFT = 'draft', "Brouillon"
        SENDING = 'sending', "Envoi en cours"
        DONE = 'done', "Terminée"
        CANCELLED = 'cancelled', "Annulée"

    subject = models.CharField(max_length=150, verbose_name="Objet")
    body = models.TextField(max_length=5000, verbose_name="Message")
    cta_label = models.CharField(max_length=40, blank=True, verbose_name="Texte du bouton")
    cta_url = models.URLField(max_length=300, blank=True, verbose_name="Lien du bouton")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PROMOTIONAL, verbose_name="Type")
    audience = models.CharField(max_length=20, choices=Audience.choices, default=Audience.ACTIVE, verbose_name="Audience")
    activity_days = models.PositiveSmallIntegerField(default=90, verbose_name="Seuil d'inactivité (jours)")
    # Membres choisis pour l'audience « liste personnalisée » : vidée au lancement (les destinataires sont alors figés à part)
    custom_members = models.ManyToManyField('BeerUser', blank=True, related_name='+', verbose_name="Membres choisis")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name="Rédigée par")
    launched_at = models.DateTimeField(null=True, blank=True, editable=False)
    launched_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', editable=False, verbose_name="Lancée par")
    finished_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Campagne e-mail"
        verbose_name_plural = "Campagnes e-mail"

    def __str__(self):
        return self.subject

    @property
    def is_promotional(self):
        return self.kind == self.Kind.PROMOTIONAL


class CampaignRecipient(models.Model):
    """Un membre visé par une campagne et l'état de son envoi. Supprimé avec le compte (aucune adresse n'est copiée ici)."""

    class Status(models.TextChoices):
        PENDING = 'pending', "En attente"
        SENDING = 'sending', "En cours"  # réservé : jamais renvoyé, pour qu'un incident n'envoie pas deux fois
        SENT = 'sent', "Envoyé"
        FAILED = 'failed', "Échec"
        SKIPPED = 'skipped', "Ignoré"  # désinscrit, suspendu ou campagne annulée avant l'envoi

    campaign = models.ForeignKey(EmailCampaign, on_delete=models.CASCADE, related_name='recipients')
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='+')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['campaign', 'user'], name='unique_campaign_recipient')]
        indexes = [models.Index(fields=['campaign', 'status'], name='campaign_recipient_status_idx')]
