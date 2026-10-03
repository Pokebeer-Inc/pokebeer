"""Trophées : difficulté réelle de chaque trophée d'après la progression des membres."""
from collections import defaultdict

from django.db.models import Count

from ...models import UserAchievementState
from ..achievements import TIER_NAMES
from .blocks import Chart, Kpi, Note, Table

TOO_EASY = 70      # % de membres ayant au moins le palier Bronze
HARD = 10
VERY_HARD = 2


def difficulty(unlock_rate):
    if unlock_rate > TOO_EASY:
        return 'Trop facile ?'
    if unlock_rate < VERY_HARD:
        return 'Très difficile ?'
    if unlock_rate < HARD:
        return 'Difficile'
    return 'Équilibré'


def build(period, params):
    members = UserAchievementState.objects.values('user').distinct().count()
    by_trophy = defaultdict(lambda: [0] * len(TIER_NAMES))
    for row in UserAchievementState.objects.values('achievement_name', 'tier_level').annotate(n=Count('pk')):
        by_trophy[row['achievement_name']][min(row['tier_level'], len(TIER_NAMES) - 1)] += row['n']
    names = sorted(by_trophy)

    def rate(count):
        return round(count / members * 100, 1) if members else 0

    chart = Chart('tiers', 'Membres par palier et par trophée', 'bar', names,
                  [{'name': TIER_NAMES[tier], 'data': [by_trophy[name][tier] for name in names]} for tier in range(len(TIER_NAMES))],
                  stacked=True, subtitle='« Bloqué » : le membre n\'a pas encore atteint le premier palier')

    rows = []
    for name in names:
        tiers = by_trophy[name]
        unlocked = sum(tiers[1:])
        rows.append([name, rate(unlocked), rate(tiers[len(tiers) - 1]), difficulty(rate(unlocked))])
    rows.sort(key=lambda r: -r[1])

    return [
        Kpi('Membres évalués', members, hint='membres dont les trophées ont déjà été calculés'),
        chart,
        Table('difficulty', 'Difficulté des trophées', ['Trophée', '% ayant débloqué (Bronze+)', '% au palier maximal', 'Verdict'], rows,
              subtitle=f'Trop facile au-dessus de {TOO_EASY} %, difficile sous {HARD} %, très difficile sous {VERY_HARD} %'),
        Note("Les trophées cachés (ex. Irlandais, Copain de Gaétan) sont volontairement rares : un faible taux y est normal. "
             "Les seuils de chaque trophée se règlent dans services/achievements.py."),
    ]
