"""Goûts : ce que les membres boivent et apprécient (styles, force, amertume, notes, demande non satisfaite)."""
from collections import defaultdict

from django.db.models import Avg, Count
from django.db.models.functions import ExtractMonth

from ...models import Beer, Drinks
from .blocks import Chart, Note, Table
from .series import growth, month_name

MIN_STYLE_VOLUME = 5  # sous ce volume, une variation en % n'est que du bruit
MIN_RATINGS = 3

ABV_BUCKETS = ((0, 4, '< 4 %'), (4, 5, '4–5 %'), (5, 6, '5–6 %'), (6, 7.5, '6–7,5 %'), (7.5, 9, '7,5–9 %'), (9, 101, '≥ 9 %'))
IBU_BUCKETS = ((0, 15, '< 15'), (15, 30, '15–30'), (30, 45, '30–45'), (45, 60, '45–60'), (60, 10_000, '≥ 60'))


def split_styles(raw):
    """« IPA, NEIPA / Hazy » compte pour chacun de ses styles."""
    return [name.strip() for name in (raw or '').split(',') if name.strip()]


def style_stats(drinks):
    """{style: (nombre de dégustations, somme des notes, nombre de notes)} sur un queryset de dégustations."""
    stats = defaultdict(lambda: [0, 0.0, 0])
    rows = drinks.values('beer_id__style').annotate(n=Count('pk'), rated=Count('note'), avg=Avg('note'))
    for row in rows:
        for style in split_styles(row['beer_id__style']):
            stats[style][0] += row['n']
            stats[style][1] += (row['avg'] or 0) * row['rated']
            stats[style][2] += row['rated']
    return stats


def _average(total, count):
    return round(total / count, 2) if count else None


def _bucketed(rows, buckets, key):
    counts = [0] * len(buckets)
    for row in rows:
        value = row[key]
        if value is None:
            continue
        for index, (low, high, _label) in enumerate(buckets):
            if low <= float(value) < high:
                counts[index] += row['n']
                break
    return [label for *_ignored, label in buckets], counts


def build(period, params):
    current = Drinks.objects.filter(date__gte=period.start)
    previous = Drinks.objects.filter(date__gte=period.previous_start, date__lt=period.start)
    blocks = []

    now_stats, before_stats = style_stats(current), style_stats(previous)
    ranked = sorted(now_stats.items(), key=lambda item: -item[1][0])
    blocks.append(Chart('styles-volume', 'Styles les plus bus', 'hbar', [s for s, _ in ranked[:15]],
                        [{'name': 'Dégustations', 'data': [v[0] for _, v in ranked[:15]]}],
                        subtitle='Un style composé compte pour chacun de ses styles'))

    best = sorted(((s, _average(v[1], v[2]), v[2]) for s, v in now_stats.items() if v[2] >= MIN_RATINGS), key=lambda r: -r[1])[:10]
    blocks.append(Chart('styles-rating', 'Styles les mieux notés', 'hbar', [s for s, _, _ in best],
                        [{'name': 'Note moyenne /10', 'data': [r[1] for r in best]}],
                        subtitle=f'Au moins {MIN_RATINGS} notes par style'))

    movers = []
    for style, (count, _total, _n) in now_stats.items():
        before = before_stats.get(style, (0,))[0]
        if count + before >= MIN_STYLE_VOLUME:
            movers.append((style, count, before, growth(count, before)))
    movers.sort(key=lambda r: (-(r[3] if r[3] is not None else 10_000), -r[1]))
    blocks.append(Table('styles-movers', 'Styles en hausse / en baisse', ['Style', 'Période', 'Précédente', 'Variation'],
                        [[s, c, b, '—' if g is None else f'{g:+.0f} %'] for s, c, b, g in movers[:12]],
                        subtitle=f'Styles avec au moins {MIN_STYLE_VOLUME} dégustations sur les deux périodes'))

    for chart_id, title, field_name, buckets in (
        ('abv', 'Force des bières bues', 'beer_id__degree', ABV_BUCKETS),
        ('ibu', 'Amertume des bières bues (IBU)', 'beer_id__bitterness', IBU_BUCKETS),
    ):
        rows = current.values(field_name).annotate(n=Count('pk'))
        labels, counts = _bucketed(rows, buckets, field_name)
        blocks.append(Chart(chart_id, title, 'bar', labels, [{'name': 'Dégustations', 'data': counts}]))

    ratings = {row['note']: row['n'] for row in current.exclude(note__isnull=True).values('note').annotate(n=Count('pk'))}
    blocks.append(Chart('ratings', 'Répartition des notes', 'bar', [str(n) for n in range(11)],
                        [{'name': 'Avis', 'data': [ratings.get(n, 0) for n in range(11)]}],
                        subtitle='Des notes toutes élevées ou toutes basses signalent un manque de discrimination'))

    top_beers = (current.values('beer_id__name', 'beer_id__brewery_id__name')
                 .annotate(n=Count('pk'), avg=Avg('note'), rated=Count('note')).filter(rated__gte=MIN_RATINGS).order_by('-avg', '-n')[:10])
    blocks.append(Table('top-beers', 'Bières les mieux notées', ['Bière', 'Brasserie', 'Dégustations', 'Note moyenne'],
                        [[r['beer_id__name'], r['beer_id__brewery_id__name'], r['n'], round(r['avg'], 2)] for r in top_beers],
                        subtitle=f'Au moins {MIN_RATINGS} notes'))

    wished = Beer.objects.filter(is_deleted=False).annotate(w=Count('wishlisted_by')).filter(w__gt=0).order_by('-w')[:10]
    blocks.append(Table('wishlist', 'Demande non satisfaite : bières les plus souhaitées', ['Bière', 'Brasserie', 'Listes de souhaits'],
                        [[b.name, b.brewery_id.name, b.w] for b in wished.select_related('brewery_id')],
                        subtitle='Bières que des membres veulent goûter : un levier de mise en avant pour les brasseurs'))

    top_styles = [s for s, _ in ranked[:6]]
    seasonal = defaultdict(lambda: defaultdict(int))
    for row in current.annotate(m=ExtractMonth('date')).values('beer_id__style', 'm').annotate(n=Count('pk')):
        for style in split_styles(row['beer_id__style']):
            if style in top_styles:
                seasonal[style][row['m']] += row['n']
    blocks.append(Chart('seasonality', 'Saisonnalité des styles principaux', 'heatmap', [month_name(m) for m in range(1, 13)],
                        [{'name': s, 'data': [seasonal[s][m] for m in range(1, 13)]} for s in top_styles],
                        subtitle='Mois de dégustation ; lisible surtout avec 12 mois ou plus'))
    blocks.append(Note("Les notes sont libres et subjectives : comparez les styles entre eux plutôt que les valeurs absolues."))
    return blocks
