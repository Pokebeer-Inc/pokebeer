"""Rappel discret aux membres dont une dégustation récente n'a aucun contexte (ni lieu, ni format, ni prix).

Ces informations sont facultatives mais ce sont elles qui rendent les statistiques utiles aux brasseries et aux bars. Le rappel est rare par
construction : un membre n'en reçoit qu'un à la fois, au plus un tous les COOLDOWN, et seulement pour une dégustation vieille de plus d'un
jour (pas pendant qu'il la saisit). Sa catégorie de préférences est « Trophées » : il se désactive avec elle, ou avec toutes les notifications.
"""
from datetime import timedelta

from django.utils import timezone

from ...models import Drinks, Notification
from ..messaging.notifications import notify

TYPE = 'context_reminder'
AFTER = timedelta(days=1)
WINDOW = timedelta(days=7)
COOLDOWN = timedelta(days=14)
BATCH = 200


def candidates(now):
    """La dernière dégustation sans contexte de chaque membre à relancer (un seul rappel par membre)."""
    already = Notification.objects.filter(notif_type=TYPE, created_at__gte=now - COOLDOWN).values('recipient')
    return (Drinks.objects
            .filter(created_at__gte=now - WINDOW, created_at__lte=now - AFTER, venue_type='', serving_format='', price__isnull=True,
                    drinker__is_active=True, drinker__onboarding_done=True, beer__is_deleted=False)
            .exclude(drinker__in=already)
            .select_related('beer', 'drinker')
            .order_by('drinker', '-created_at').distinct('drinker')[:BATCH])


def send_pending(now=None):
    """Envoie les rappels dus ; renvoie le nombre de notifications réellement créées (la politique d'envoi peut en écarter)."""
    now = now or timezone.now()
    return sum(len(notify(TYPE, [drink.drinker], beer=drink.beer)) for drink in candidates(now))
