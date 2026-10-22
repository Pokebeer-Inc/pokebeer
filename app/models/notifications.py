"""Notifications et état des trophées."""

from django.db import models
from django.utils import timezone

from ..fields import PublicSlugField
from ..domain import notification_types

class Notification(models.Model):
    """Notification adressée à un membre. Le modèle ne décide pas qui peut la recevoir (préférences, blocages) : toute création passe par
    services/messaging/notifications.py, qui applique la politique d'envoi."""
    slug = PublicSlugField()
    
    NOTIFICATION_TYPES = notification_types.CHOICES

    recipient = models.ForeignKey('BeerUser', on_delete=models.CASCADE, related_name='notifications')
    sender = models.ForeignKey('BeerUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications')
    notif_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    report = models.ForeignKey('Report', on_delete=models.CASCADE, null=True, blank=True)
    feedback = models.ForeignKey('Feedback', on_delete=models.CASCADE, null=True, blank=True)
    
    beer = models.ForeignKey('Beer', on_delete=models.CASCADE, null=True, blank=True)
    brewery = models.ForeignKey('Brewery', on_delete=models.CASCADE, null=True, blank=True)
    bar = models.ForeignKey('Bar', on_delete=models.CASCADE, null=True, blank=True)
    spot = models.ForeignKey('BeerSpot', on_delete=models.CASCADE, null=True, blank=True)
    achievement_slug = models.CharField(max_length=100, null=True, blank=True)  # identifiant stable du trophée (voir services/members/achievements.py)
    achievement_tier = models.PositiveSmallIntegerField(null=True, blank=True)  # palier atteint (1 = Bronze… 4 = Platine) : retiré s'il est perdu
    text_content = models.CharField(max_length=255, null=True, blank=True) 
    
    is_read = models.BooleanField(default=False)
    # Instant où la notification a été montrée (pop-up ou push natif) : une même alerte ne s'affiche jamais deux fois,
    # contrairement à `is_read` qui reste faux jusqu'au clic.
    toasted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at'], name='notif_recipient_unread_idx'),  # liste, pop-ups, compteur de non lues
        ]

    def __str__(self):
        return f"{self.notif_type} -> {self.recipient_id}"

    FORMER_MEMBER = "Un ancien membre"  # expéditeur dont le compte a été supprimé (le lien est mis à NULL, la notification reste)

    @property
    def sender_name(self):
        """Pseudo de l'expéditeur pour le texte de la notification, jamais vide : un compte supprimé n'a plus de pseudo à afficher."""
        return self.sender.username if self.sender_id else self.FORMER_MEMBER

    @property
    def place(self):
        """Établissement concerné (brasserie ou bar)."""
        return self.brewery or self.bar

    @property
    def image_url(self):
        """Image illustrant la notification (avatar, bière, établissement) ou None : voir NotificationType.image_for."""
        return notification_types.get(self.notif_type).image_for(self)

    @property
    def text_template(self):
        """Gabarit du texte de cette notification (un par type)."""
        return notification_types.get(self.notif_type).text_template

    @property
    def visual(self):
        return notification_types.get(self.notif_type).visual

    @property
    def time_ago(self):
        now = timezone.now()
        diff = now - self.created_at
        
        if diff.days > 0:
            return f"{diff.days} j"
        
        hours = diff.seconds // 3600
        if hours > 0:
            return f"{hours}h"
            
        minutes = (diff.seconds % 3600) // 60
        if minutes > 0:
            return f"{minutes} min"
            
        return "à l'instant"
    
class UserAchievementState(models.Model):
    """Mémorise les trophées déjà débloqués par l'utilisateur pour ne pas le spammer"""
    user = models.ForeignKey('BeerUser', on_delete=models.CASCADE)
    achievement_slug = models.CharField(max_length=100)
    tier_level = models.IntegerField(default=0)
    
    class Meta:
        unique_together = ('user', 'achievement_slug')

    def __str__(self):
        return f"{self.achievement_slug} niveau {self.tier_level} ({self.user_id})"
