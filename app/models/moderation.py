"""Journal des contenus soumis à la modération."""

from django.db import models


    
class ModerationEntryQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(reviewed_at__isnull=True)

    def for_object(self, kind, object_id):
        return self.filter(kind=kind, object_id=object_id)


class ModerationEntry(models.Model):
    """Trace d'un contenu public créé ou modifié, à relire par l'équipe. N'empêche jamais la publication."""

    class Kind(models.TextChoices):
        BEER = 'beer', 'Bière'
        COMMENT = 'comment', 'Commentaire'
        BREWERY = 'brewery', 'Brasserie'
        BAR = 'bar', 'Bar'
        USER = 'user', 'Membre'

    class Action(models.TextChoices):
        CREATED = 'created', 'Création'
        MODIFIED = 'modified', 'Modification'

    kind = models.CharField(max_length=20, choices=Kind.choices)
    action = models.CharField(max_length=10, choices=Action.choices)
    object_id = models.PositiveBigIntegerField(verbose_name="Identifiant de l'objet")
    label = models.CharField(max_length=255, verbose_name="Libellé")
    context = models.CharField(max_length=255, blank=True, verbose_name="Contexte")
    # [{"field", "label", "image", "old", "new"}] : valeurs au moment de l'enregistrement
    changes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name="Validé par")
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="Validé le")

    objects = ModerationEntryQuerySet.as_manager()

    class Meta:
        verbose_name = "Contenu à valider"
        verbose_name_plural = "Contenus à valider"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reviewed_at', 'kind', 'action'], name='moderation_queue_idx'),
            models.Index(fields=['kind', 'object_id'], name='moderation_object_idx'),
        ]

    def __str__(self):
        return f"{self.get_action_display()} - {self.get_kind_display()} - {self.label}"
