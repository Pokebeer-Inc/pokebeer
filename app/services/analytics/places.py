"""Établissements et aide à la décision : classement, et pistes de mise en avant pour une brasserie donnée."""

from django.db.models import Avg, Count

from ...models import Brewery, Drinks
from . import brewery_report
from .blocks import Note, Table
from .series import growth

TOP = 15


def _leaderboard(period):
    current = {r['beer__brewery']: r for r in
               Drinks.objects.filter(date__gte=period.start, beer__brewery__isnull=False).values('beer__brewery', 'beer__brewery__name')
               .annotate(n=Count('pk'), avg=Avg('note'), beers=Count('beer', distinct=True))}
    before = {r['beer__brewery']: r['n'] for r in
              Drinks.objects.filter(date__gte=period.previous_start, date__lt=period.start)
              .values('beer__brewery').annotate(n=Count('pk'))}
    rows = sorted(current.values(), key=lambda r: -r['n'])[:TOP]
    return Table('breweries', 'Brasseries les plus bues', ['Brasserie', 'Dégustations', 'Bières bues', 'Note moyenne', 'Variation'],
                 [[r['beer__brewery__name'], r['n'], r['beers'], round(r['avg'], 2) if r['avg'] is not None else '—',
                   '—' if growth(r['n'], before.get(r['beer__brewery'], 0)) is None
                   else f"{growth(r['n'], before.get(r['beer__brewery'], 0)):+.0f} %"] for r in rows],
                 subtitle='Variation par rapport à la période précédente de même durée')


def build(period, params):
    blocks = [_leaderboard(period)]

    slug = params.get('brewery', '')
    brewery = Brewery.objects.filter(slug=slug).first() if slug else None
    if brewery:
        blocks += brewery_report.BreweryReport(brewery, period).blocks()
    else:
        blocks.append(Note("Choisissez une brasserie ci-dessus pour obtenir son rapport complet : audience, contexte, prix, fidélité, prévision et pistes de mise en avant."))
    return blocks
