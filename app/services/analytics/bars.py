"""Bars : activité des membres autour de chaque bar. Le détail d'un bar est son rapport (bar_report.py)."""
from ...models import Bar
from .bar_report import HIDDEN, NEAR_BAR_M, BarReport, spots_near
from .blocks import Note, Table
from .privacy import MIN_GROUP_SIZE, is_publishable
from .spots import spot_points


def _overview(bars, points):
    rows = []
    for bar in bars:
        near = spots_near(bar, points)
        members = len({p.user_id for p in near})
        rows.append((bar.name, len(near), members))
    rows.sort(key=lambda r: -r[1])
    return Table('bars-overview', 'Activité autour de chaque bar', ['Bar', 'Lieux à proximité', 'Membres'],
                 [[name, spots if is_publishable(members) else HIDDEN, members if is_publishable(members) else HIDDEN]
                  for name, spots, members in rows[:25]],
                 subtitle=f'Lieux placés à moins de {NEAR_BAR_M} m du bar ; en dessous de {MIN_GROUP_SIZE} membres, les chiffres sont masqués')


def build(period, params):
    bars = list(Bar.objects.filter(latitude__isnull=False, longitude__isnull=False).order_by('name'))
    blocks = [_overview(bars, spot_points(period))]

    bar = next((b for b in bars if b.slug == params.get('bar')), None)
    if not bar:
        blocks.append(Note("Choisissez un bar ci-dessus pour voir ce que les membres boivent autour de lui."))
        return blocks
    return blocks + BarReport(bar, period).blocks()
