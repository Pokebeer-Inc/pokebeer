"""Habitudes : quand et comment les membres utilisent Pokebeer (rythme, régularité, fidélisation, adoption)."""
from django.db.models import Count
from django.db.models.functions import ExtractIsoWeekDay, ExtractMonth, TruncMonth

from ...models import BeerUser, Drinks
from .blocks import Chart, Kpi, Table
from .periods import _add_months, _first_of_month
from .series import month_name

WEEKDAYS = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
INTENSITY_BUCKETS = ((1, 1, '1 dégustation'), (2, 5, '2 à 5'), (6, 20, '6 à 20'), (21, 10 ** 9, 'Plus de 20'))
COHORT_MONTHS = 6  # cohortes de nouveaux membres suivies
RETENTION_OFFSETS = (0, 1, 2, 3)


def _percent(part, total):
    return round(part / total * 100, 1) if total else 0


def _retention(period):
    """Pour chaque mois d'inscription : part des inscrits ayant dégusté au moins une bière M+0, M+1, M+2, M+3."""
    first = _first_of_month(period.today, COHORT_MONTHS - 1)
    sizes = {
        row['cohort'].date() if hasattr(row['cohort'], 'date') else row['cohort']: row['n']
        for row in BeerUser.objects.filter(created_at__date__gte=first).annotate(cohort=TruncMonth('created_at'))
        .values('cohort').annotate(n=Count('pk'))
    }
    rows = (Drinks.objects.filter(drinker_id__created_at__date__gte=first)
            .annotate(cohort=TruncMonth('drinker_id__created_at'), active=TruncMonth('date'))
            .values('cohort', 'active').annotate(users=Count('drinker_id', distinct=True)))
    counts = {}
    for row in rows:
        cohort = row['cohort'].date() if hasattr(row['cohort'], 'date') else row['cohort']
        active = row['active'].date() if hasattr(row['active'], 'date') else row['active']
        counts[(cohort, active)] = row['users']

    table_rows = []
    for cohort in sorted(sizes):
        row = [cohort.strftime('%Y-%m'), sizes[cohort]]
        for offset in RETENTION_OFFSETS:
            month = _add_months(cohort, offset)
            row.append('—' if month > period.today else f"{_percent(counts.get((cohort, month), 0), sizes[cohort])} %")
        table_rows.append(row)
    return Table('retention', 'Fidélisation des nouveaux membres', ['Inscrits en', 'Membres', 'M+0', 'M+1', 'M+2', 'M+3'], table_rows,
                 subtitle='Part des inscrits d\'un mois ayant noté au moins une bière, le mois même puis les suivants')


def build(period, params):
    drinks = Drinks.objects.filter(date__gte=period.start)
    blocks = []

    weekday = {row['d']: row['n'] for row in drinks.annotate(d=ExtractIsoWeekDay('date')).values('d').annotate(n=Count('pk'))}
    blocks.append(Chart('weekday', 'Dégustations par jour de la semaine', 'bar', WEEKDAYS,
                        [{'name': 'Dégustations', 'data': [weekday.get(i, 0) for i in range(1, 8)]}],
                        subtitle='Jour de la dégustation déclarée : à utiliser pour choisir les jours de mise en avant'))

    month = {row['m']: row['n'] for row in drinks.annotate(m=ExtractMonth('date')).values('m').annotate(n=Count('pk'))}
    blocks.append(Chart('month-of-year', 'Dégustations par mois de l\'année', 'bar', [month_name(m) for m in range(1, 13)],
                        [{'name': 'Dégustations', 'data': [month.get(m, 0) for m in range(1, 13)]}],
                        subtitle='Saisonnalité ; 12 mois ou plus recommandés'))

    per_member = [row['n'] for row in drinks.values('drinker_id').annotate(n=Count('pk'))]
    members = len(per_member)
    counts = [sum(1 for n in per_member if low <= n <= high) for low, high, _ in INTENSITY_BUCKETS]
    blocks.append(Chart('intensity', 'Régularité des membres actifs', 'donut', [label for *_x, label in INTENSITY_BUCKETS], [{'name': 'Membres', 'data': counts}],
                        subtitle=f'{members} membre(s) actif(s) sur la période, par nombre de dégustations'))
    if members:
        average = round(sum(per_member) / members, 1)
        blocks.insert(0, Kpi('Dégustations par membre actif', average, hint='moyenne sur la période'))

    blocks.append(_retention(period))

    total = BeerUser.objects.filter(is_active=True).count()
    adoption = [
        ('Au moins une note', BeerUser.objects.filter(is_active=True, drinks__isnull=False).distinct().count()),
        ('Commente ses avis', BeerUser.objects.filter(is_active=True, drinks__comment__gt='').distinct().count()),
        ('Place des lieux', BeerUser.objects.filter(is_active=True, spots__isnull=False).distinct().count()),
        ('Suit d\'autres membres', BeerUser.objects.filter(is_active=True, following__isnull=False).distinct().count()),
        ('Est suivi', BeerUser.objects.filter(is_active=True, followers__isnull=False).distinct().count()),
        ('Utilise un carnet', BeerUser.objects.filter(is_active=True, custom_notebooks__isnull=False).distinct().count()),
        ('Liste de souhaits', BeerUser.objects.filter(is_active=True, wishlist_beers__isnull=False).distinct().count()),
    ]
    blocks.append(Chart('adoption', 'Adoption des fonctionnalités', 'hbar', [label for label, _ in adoption],
                        [{'name': '% des membres actifs', 'data': [_percent(n, total) for _, n in adoption]}],
                        subtitle=f'Sur {total} membre(s) actif(s) : repère les fonctionnalités à promouvoir ou à simplifier'))
    return blocks
