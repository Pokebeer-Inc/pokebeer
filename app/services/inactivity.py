"""RGPD : suppression des comptes inactifs.

Un compte est inactif quand `last_activity_at` dépasse INACTIVE_ACCOUNT_MONTHS. Le membre est d'abord prévenu par
notification, puis supprimé une fois le délai de grâce écoulé : jamais de suppression sans préavis, même si la tâche
planifiée a manqué des jours. Les comptes suspendus (modération), le staff et les superusers ne sont jamais supprimés.
"""
import calendar
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.formats import date_format

from ..models import STAFF_GROUP, AccountDeletion, BeerUser, Notification
from .notifications import notify

logger = logging.getLogger(__name__)

NOTIFICATION = 'inactivity_warning'
ACTIVITY_REFRESH = timedelta(hours=12)  # évite une écriture en base à chaque requête


def _months_before(moment, months):
    index = moment.year * 12 + moment.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    return moment.replace(year=year, month=month, day=min(moment.day, calendar.monthrange(year, month)[1]))


def warning_period():
    return timedelta(days=settings.INACTIVE_ACCOUNT_WARNING_DAYS)


def inactivity_limit(now=None):
    """Dernière activité antérieure à cet instant = compte inactif."""
    return _months_before(now or timezone.now(), settings.INACTIVE_ACCOUNT_MONTHS)


def deletion_date(user):
    """Date prévue de suppression d'un compte (au plus tôt : le préavis doit aussi être écoulé)."""
    due = _months_after(user.last_activity_at, settings.INACTIVE_ACCOUNT_MONTHS)
    if user.inactivity_warned_at:
        due = max(due, user.inactivity_warned_at + warning_period())
    return due


def _months_after(moment, months):
    return _months_before(moment, -months)


def candidates():
    """Comptes soumis à la règle (hors suspendus, staff et superusers)."""
    return BeerUser.objects.filter(is_active=True, is_superuser=False).exclude(groups__name=STAFF_GROUP)


def record_activity(user):
    """Enregistre une visite ; une visite annule l'avertissement en cours."""
    now = timezone.now()
    warned = user.inactivity_warned_at is not None
    if not warned and now - user.last_activity_at < ACTIVITY_REFRESH:
        return
    BeerUser.objects.filter(pk=user.pk).update(last_activity_at=now, inactivity_warned_at=None)
    user.last_activity_at, user.inactivity_warned_at = now, None
    if warned:
        # L'avertissement n'a plus lieu d'être : il ne doit pas rester dans la liste
        Notification.objects.filter(recipient=user, notif_type=NOTIFICATION).delete()


def to_warn(now=None):
    """Comptes entrés dans la période de préavis et pas encore prévenus."""
    now = now or timezone.now()
    return candidates().filter(
        last_activity_at__lte=inactivity_limit(now) + warning_period(), inactivity_warned_at__isnull=True,
    )


def due_for_deletion(now=None):
    """Comptes inactifs, prévenus, dont le préavis est écoulé."""
    now = now or timezone.now()
    return candidates().filter(
        last_activity_at__lte=inactivity_limit(now), inactivity_warned_at__lte=now - warning_period(),
    )


def warn_users(now=None):
    """Prévient chaque compte concerné par notification (application et push) ; renvoie le nombre de membres prévenus."""
    now = now or timezone.now()
    warned = 0
    for user in to_warn(now).iterator():
        deadline = max(deletion_date(user), now + warning_period())
        notify(NOTIFICATION, [user], text_content=date_format(deadline, 'j F Y'))
        BeerUser.objects.filter(pk=user.pk).update(inactivity_warned_at=now)
        warned += 1
    return warned


def delete_account(user, reason, was_warned=None):
    """Supprime un compte et en garde la trace, sans donnée personnelle."""
    with transaction.atomic():
        AccountDeletion.objects.create(
            user_id=user.pk, reason=reason, last_activity_at=user.last_activity_at,
            was_warned=user.inactivity_warned_at is not None if was_warned is None else was_warned,
        )
        user.delete()


def purge_inactive_accounts(now=None):
    """Prévient puis supprime ; renvoie (prévenus, supprimés)."""
    now = now or timezone.now()
    deleted = 0
    for user in due_for_deletion(now).iterator():
        try:
            delete_account(user, AccountDeletion.Reason.INACTIVITY)
            deleted += 1
        except Exception:  # un compte en échec ne bloque pas les autres
            logger.exception("Suppression du compte %s impossible", user.pk)
    return warn_users(now), deleted


def dashboard_stats(now=None):
    """Chiffres du tableau de bord de l'admin."""
    now = now or timezone.now()
    awaiting = due_for_deletion(now).count()
    unwarned_overdue = candidates().filter(
        last_activity_at__lte=inactivity_limit(now), inactivity_warned_at__isnull=True,
    ).count()
    warned = candidates().filter(inactivity_warned_at__isnull=False)
    deletions = AccountDeletion.objects
    since = now - timedelta(days=30)
    return {
        'months': settings.INACTIVE_ACCOUNT_MONTHS,
        'warning_days': settings.INACTIVE_ACCOUNT_WARNING_DAYS,
        'to_warn': to_warn(now).count(),
        'unwarned_overdue': unwarned_overdue,
        'awaiting_deletion': awaiting,
        'warned': warned.count(),
        'upcoming': sorted(({'user': u, 'date': deletion_date(u)} for u in warned.order_by('inactivity_warned_at')[:50]), key=lambda item: item['date'])[:10],
        'deleted_total': deletions.count(),
        'deleted_inactivity': deletions.filter(reason=AccountDeletion.Reason.INACTIVITY).count(),
        'deleted_30d': deletions.filter(deleted_at__gte=since).count(),
        'recent_deletions': list(deletions.all()[:10]),
    }
