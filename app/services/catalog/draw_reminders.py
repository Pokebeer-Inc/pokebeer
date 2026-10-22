"""Rappel quotidien « votre tirage du jour est prêt » (à 18 h, heure de Paris), envoyé en push aux membres de l'application Android qui n'ont pas encore tiré.

Seuls les membres dont l'appareil est enregistré le reçoivent : sur le site, la carte de l'accueil suffit et la liste des notifications
ne se remplirait pas d'un message par jour. Un nouveau rappel remplace l'ancien s'il n'a pas été lu. Sa catégorie de préférences est
« Trophées et récompenses » : il se désactive avec elle, avec toutes les notifications, ou avec l'interrupteur du tirage du jour.
"""
from django.utils import timezone

from ...models import BeerUser, DailyDraw, Notification
from ..messaging.notifications import notify

TYPE = 'daily_draw'
SEND_HOUR = 18  # heure locale (Europe/Paris) : la tâche planifiée tourne en UTC, donc à deux heures (été et hiver) dont une seule convient
BATCH = 500


def _due(now):
    """Membres actifs avec un appareil, sans tirage ni rappel aujourd'hui."""
    local = timezone.localtime(now)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    drawn = DailyDraw.objects.filter(day=local.date()).values('user')
    reminded = Notification.objects.filter(notif_type=TYPE, created_at__gte=start).values('recipient')
    return (BeerUser.objects
            .filter(is_active=True, onboarding_done=True, daily_draw_enabled=True, fcm_token__isnull=False)
            .exclude(fcm_token='')
            .exclude(pk__in=drawn)
            .exclude(pk__in=reminded))


def send_pending(now=None):
    """Envoie les rappels dus, seulement à SEND_HOUR heure locale ; renvoie le nombre de notifications réellement créées (la politique
    d'envoi peut en écarter)."""
    now = now or timezone.now()
    if timezone.localtime(now).hour != SEND_HOUR:
        return 0
    sent = 0
    last = 0
    while True:
        members = list(_due(now).filter(pk__gt=last).order_by('pk')[:BATCH])  # par clé croissante : un membre écarté par ses préférences n'est pas repris
        if not members:
            return sent
        last = members[-1].pk
        Notification.objects.filter(notif_type=TYPE, recipient__in=members, is_read=False).delete()
        sent += len(notify(TYPE, members))
