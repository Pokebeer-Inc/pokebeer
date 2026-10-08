"""Échanges d'un membre avec l'équipe."""

from django.db import models

from ..fields import PublicSlugField


class Feedback(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('replied', 'Répondu'),
    ]
    
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='feedbacks', verbose_name="Utilisateur")
    slug = PublicSlugField()  # jeton opaque : l'échange est privé
    message = models.TextField(verbose_name="Message / Suggestion")  # premier message du membre ; la suite est dans FeedbackMessage
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Statut")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date")

    class Meta:
        verbose_name = "Feedback / Suggestion"
        ordering = ['-created_at']

    @property
    def last_team_message(self):
        """Dernière réponse de l'équipe, utilisée par le texte des notifications."""
        from ..services.feedback import last_team_message
        return last_team_message(self)

    def __str__(self):
        return f"Feedback de {self.user.username} ({self.get_status_display()})"
    
class FeedbackMessage(models.Model):
    """Message d'un échange avec l'équipe, après le premier message du membre (stocké dans Feedback.message)."""
    class Author(models.TextChoices):
        MEMBER = 'member', 'Membre'
        TEAM = 'team', 'Équipe'

    feedback = models.ForeignKey(Feedback, on_delete=models.CASCADE, related_name='messages')
    author_kind = models.CharField(max_length=10, choices=Author.choices)
    author = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='feedback_messages')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']

    def __str__(self):
        return f"{self.get_author_kind_display()} : {self.body[:40]}"
