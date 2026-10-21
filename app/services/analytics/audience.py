"""Audience : qui sont les membres qui boivent (âge, genre) et ce que chaque segment aime.

Les données viennent de l'inscription (date de naissance, genre facultatif) et ne sortent qu'en tranches agrégées d'au moins
MIN_GROUP_SIZE dégustateurs distincts. C'est la matière des études de marché vendues aux brasseurs : « qui boit mes bières ? ».
"""
from statistics import mean

from .formatting import fr
from ...models import BeerUser, Drinks
from .blocks import Chart, Kpi, Note
from .profiles import AGE_BANDS, GENDER_LABELS, UNDISCLOSED, age_on, audience_blocks, demographic_members, segment_totals, segments, style_by_segment

AGE_ORDER = [label for *_x, label in AGE_BANDS]
GENDER_ORDER = list(GENDER_LABELS.values())


def _segment_charts(drinks, seg, index, key, label, order):
    totals = segment_totals(drinks, seg, index)
    names = [name for name in order if name in totals]
    if not names:
        return []
    return [
        Chart(f'{key}-intensity', f'Dégustations par membre actif · {label}', 'bar', names,
              [{'name': 'Dégustations par membre', 'data': [round(totals[n]['tastings'] / len(totals[n]['drinkers']), 1) for n in names]}],
              subtitle='Intensité d\'usage : quels segments notent le plus'),
        Chart(f'{key}-rating', f'Note moyenne · {label}', 'bar', names,
              [{'name': 'Note moyenne /10', 'data': [round(totals[n]['note_sum'] / totals[n]['rated'], 2) if totals[n]['rated'] else 0 for n in names]}],
              subtitle='Les segments ne notent pas tous avec la même sévérité : comparez les écarts, pas les valeurs absolues'),
    ]


def build(period, params):
    drinks = Drinks.objects.filter(date__gte=period.start)
    today = period.today
    members = BeerUser.objects.filter(is_active=True)
    total = members.count()
    counted = demographic_members().filter(is_active=True)
    ages = [age_on(birth, today) for birth in counted.filter(birth_date__isnull=False).values_list('birth_date', flat=True)]
    with_gender = counted.filter(gender__in=list(GENDER_LABELS)).count()
    opposed = total - counted.count()

    blocks = [
        Kpi('Membres actifs (comptes)', total),
        Kpi('Âge moyen', f'{fr(mean(ages), 1)} ans' if ages else '—', hint=f'{len(ages)} date(s) de naissance connue(s)'),
        Kpi('Genre renseigné', f'{round(with_gender / counted.count() * 100) if counted.count() else 0} %', hint='hors « je préfère ne pas dire »'),
        Kpi('Opposés aux statistiques', opposed, hint='membres exclus de tout calcul d\'âge et de genre (réglage du compte)'),
    ]
    blocks += audience_blocks(drinks, 'audience', today)

    seg = segments(drinks, today)
    for index, key, label, order in ((0, 'age', 'tranche d\'âge', AGE_ORDER), (1, 'gender', 'genre', GENDER_ORDER)):
        heatmap = style_by_segment(drinks, seg, index, f'{key}-styles', f'Styles préférés par {label}', order)
        if heatmap:
            blocks.append(heatmap)
        blocks += _segment_charts(drinks, seg, index, key, label, order)

    unknown = sum(1 for age, gender in seg.values() if age is None)
    if unknown:
        blocks.append(Note(f"{unknown} dégustateur(s) sans date de naissance connue sont exclus des tranches d'âge. "
                           f"Le genre « {UNDISCLOSED} » n'est jamais affiché."))
    blocks.append(Note("Ces statistiques sont des agrégats : aucune tranche de moins de 3 dégustateurs n'est publiée. Avant de les transmettre à "
                       "des brasseurs ou des bars, vérifiez que la politique de confidentialité en mentionne l'usage statistique."))
    return blocks
