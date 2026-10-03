"""Fenêtre temporelle des analyses : valeurs validées contre une liste blanche (jamais de saisie libre)."""
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models.functions import TruncMonth, TruncWeek
from django.utils import timezone

MONTH_CHOICES = (3, 6, 12, 24)
GRANULARITIES = {'week': ('Semaine', TruncWeek), 'month': ('Mois', TruncMonth)}
DEFAULT_MONTHS = 12
DEFAULT_GRANULARITY = 'month'


def _first_of_month(day, months_back):
    index = day.year * 12 + day.month - 1 - months_back
    return date(index // 12, index % 12 + 1, 1)


def _add_months(day, months):
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


@dataclass(frozen=True)
class Period:
    months: int = DEFAULT_MONTHS
    granularity: str = DEFAULT_GRANULARITY

    @classmethod
    def from_params(cls, params):
        """Lit ?months= et ?granularity= ; toute valeur hors liste blanche retombe sur le défaut."""
        try:
            months = int(params.get('months', DEFAULT_MONTHS))
        except (TypeError, ValueError):
            months = DEFAULT_MONTHS
        granularity = params.get('granularity', DEFAULT_GRANULARITY)
        return cls(
            months if months in MONTH_CHOICES else DEFAULT_MONTHS,
            granularity if granularity in GRANULARITIES else DEFAULT_GRANULARITY,
        )

    @property
    def today(self):
        return timezone.localdate()

    @property
    def start(self):
        return _first_of_month(self.today, self.months - 1)

    @property
    def previous_start(self):
        """Début de la période précédente, de même durée (pour les variations)."""
        return _first_of_month(self.today, 2 * self.months - 1)

    def trunc(self, field_name):
        return GRANULARITIES[self.granularity][1](field_name)

    def bucket_start(self, day):
        if self.granularity == 'week':
            return day - timedelta(days=day.weekday())
        return day.replace(day=1)

    def next_bucket(self, bucket):
        return bucket + timedelta(weeks=1) if self.granularity == 'week' else _add_months(bucket, 1)

    def buckets(self):
        """Début de chaque intervalle de la période (le dernier est en cours, donc incomplet)."""
        buckets, current = [], self.bucket_start(self.start)
        while current <= self.today:
            buckets.append(current)
            current = self.next_bucket(current)
        return buckets

    def label(self, bucket):
        return bucket.strftime('%Y-%m-%d') if self.granularity == 'week' else bucket.strftime('%Y-%m')
