"""Annonces de politique, limitation de débit, journal des suppressions et quotas."""

from django.db import models
from django.utils import timezone


class PolicyNotice(models.Model):
    """Annonce d'une modification de la politique de confidentialité à tous les membres (notification, e-mail en option)."""
    summary = models.CharField(max_length=200, verbose_name="Ce qui a changé")
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name="Publiée par")
    notified_count = models.PositiveIntegerField(default=0, verbose_name="Membres notifiés")
    notify_by_email = models.BooleanField(default=False, verbose_name="Aussi par e-mail")
    # L'e-mail part par lots quotidiens (quota du compte Gmail) : le curseur est le dernier membre déjà traité
    email_cursor = models.PositiveBigIntegerField(default=0, editable=False)
    emails_sent = models.PositiveIntegerField(default=0, verbose_name="E-mails envoyés")
    email_done = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Annonce de la politique de confidentialité"
        verbose_name_plural = "Annonces de la politique de confidentialité"


class ThrottleHit(models.Model):
    """Tentative comptabilisée par la limitation de débit. La clé (IP, pseudo…) n'est conservée que hachée."""
    scope = models.CharField(max_length=40)
    key_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=['scope', 'key_hash', 'created_at'], name='throttle_lookup_idx')]


class AccountDeletion(models.Model):
    """Journal des comptes supprimés. Volontairement sans donnée personnelle (ni pseudo, ni e-mail) : RGPD, minimisation."""

    class Reason(models.TextChoices):
        INACTIVITY = 'inactivity', "Inactivité"
        SELF = 'self', "Demande du membre"

    user_id = models.PositiveBigIntegerField(verbose_name="Identifiant du compte")
    reason = models.CharField(max_length=20, choices=Reason.choices)
    last_activity_at = models.DateTimeField(verbose_name="Dernière activité")
    was_warned = models.BooleanField(default=False, verbose_name="Prévenu avant suppression")
    deleted_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-deleted_at']
        verbose_name = "Compte supprimé"
        verbose_name_plural = "Comptes supprimés"
        
class ChatUsage(models.Model):
    """Nombre d'appels à l'IA (chat, lecture d'étiquette) d'un utilisateur sur une journée, par usage."""
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='chat_usages')
    day = models.DateField()
    scope = models.CharField(max_length=20, default='chat')
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('user', 'day', 'scope')
        verbose_name = "Utilisation de l'IA"

    def __str__(self):
        return f"{self.user.username} - {self.day} ({self.count})"
