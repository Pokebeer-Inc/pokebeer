"""Durée de conservation de chaque mesure et purge quotidienne (appelée par la tâche planifiée)."""
from datetime import timedelta

from django.utils import timezone

from ...models import ActivityDay, CatalogMiss, PageView
from . import page_views

ACTIVITY_DAYS = 800         # ~26 mois : deux années complètes de rétention et de saisonnalité, pas plus
MISS_DAYS = 180
VIEW_DAYS = 800


def _older_than(model, days, today):
    return model.objects.filter(day__lt=today - timedelta(days=days)).delete()[0]


def purge_expired(today=None):
    """Supprime ce qui a dépassé sa durée de conservation. Renvoie {mesure: lignes supprimées}."""
    today = today or timezone.localdate()
    return {
        'visitors': page_views.purge_visitors(today),
        'views': _older_than(PageView, VIEW_DAYS, today),
        'activity': _older_than(ActivityDay, ACTIVITY_DAYS, today),
        'misses': _older_than(CatalogMiss, MISS_DAYS, today),
    }
