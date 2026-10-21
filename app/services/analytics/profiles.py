"""Profil d'un ensemble de dégustations : qui boit (âge, genre) et dans quel contexte (lieu, compagnie, format, prix).

Le même calcul sert à toute la communauté (page Consommation), à une brasserie et à un bar : on lui passe le queryset de dégustations et un
préfixe d'identifiants de blocs. C'est aussi la base des futurs tableaux de bord destinés aux professionnels.

Anonymat : un groupe n'est publié que s'il compte au moins MIN_GROUP_SIZE dégustateurs distincts. L'âge et le genre ne sortent jamais
que sous forme de tranches agrégées ; la date de naissance exacte n'est jamais affichée.
"""
from collections import defaultdict
from statistics import median

from django.db.models import Avg, Count, Sum

from .formatting import euros
from ...domain.styles import split_styles
from ...models import BeerUser, Drinks
from .blocks import Chart, Kpi, Note
from .privacy import MIN_GROUP_SIZE, is_publishable

AGE_BANDS = ((0, 24, 'Moins de 25 ans'), (25, 34, '25–34 ans'), (35, 44, '35–44 ans'), (45, 54, '45–54 ans'), (55, 200, '55 ans et plus'))
GENDER_LABELS = {'femme': 'Femmes', 'homme': 'Hommes', 'autre': 'Autre'}
UNDISCLOSED = 'Non précisé'

VENUE_LABELS = dict(Drinks.VenueType.choices)
COMPANY_LABELS = dict(Drinks.Company.choices)
FORMAT_LABELS = dict(Drinks.ServingFormat.choices)
# Contenance de chaque format (en litres), pour comparer des prix payés pour des verres différents
FORMAT_LITRES = {'pint': 0.5, 'half': 0.25, 'bottle': 0.75, 'can': 0.33}

PRICE_BUCKETS = ((0, 3, '< 3 €'), (3, 4, '3–4 €'), (4, 5, '4–5 €'), (5, 6, '5–6 €'), (6, 7, '6–7 €'), (7, 8, '7–8 €'), (8, 10, '8–10 €'),
                 (10, 10_000, '≥ 10 €'))
HEATMAP_STYLES = 8


def age_on(birth_date, today):
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def age_band(birth_date, today):
    """Tranche d'âge du membre, ou None quand sa date de naissance n'est pas connue."""
    if not birth_date:
        return None
    age = age_on(birth_date, today)
    return next((label for low, high, label in AGE_BANDS if low <= age <= high), None)


def demographic_members():
    """Membres dont l'âge et le genre peuvent entrer dans une statistique : ceux qui ne s'y sont pas opposés (réglages du compte)."""
    return BeerUser.objects.filter(demographic_stats=True)


def segments(drinks, today):
    """{identifiant du dégustateur: (tranche d'âge ou None, genre)} pour les auteurs de ces dégustations qui acceptent les statistiques."""
    rows = demographic_members().filter(pk__in=drinks.values('drinker')).values_list('pk', 'birth_date', 'gender')
    return {pk: (age_band(birth, today), GENDER_LABELS.get(gender, UNDISCLOSED)) for pk, birth, gender in rows}


def published(drinks, field, label_of, **aggregates):
    """Groupes de dégustations selon `field` : ([{label, n, members, …}] triés par volume, dégustations masquées).

    Seuls les groupes d'au moins MIN_GROUP_SIZE dégustateurs distincts sont renvoyés ; les valeurs vides sont ignorées."""
    rows = drinks.values(field).annotate(n=Count('pk'), members=Count('drinker', distinct=True), **aggregates)
    shown, hidden = [], 0
    for row in rows:
        if row[field] in (None, ''):
            continue
        if is_publishable(row['members']):
            shown.append({**row, 'label': label_of(row[field])})
        else:
            hidden += row['n']
    shown.sort(key=lambda row: (-row['n'], row['label']))
    return shown, hidden


def _donut(chart_id, title, rows, subtitle, key='n', name='Dégustations'):
    return Chart(chart_id, title, 'donut', [row['label'] for row in rows], [{'name': name, 'data': [row[key] for row in rows]}], subtitle=subtitle)


def _hidden_note(hidden, title):
    return Note(f"{hidden} dégustation(s) de « {title} » masquée(s) : moins de {MIN_GROUP_SIZE} dégustateurs par catégorie.") if hidden else None


def coverage(drinks):
    """Part des dégustations où chaque information de contexte est renseignée : sans elle, les graphiques de contexte ne représentent
    qu'une partie des membres (ces champs sont facultatifs)."""
    total = drinks.count()
    if not total:
        return {}
    return {
        'Lieu': drinks.exclude(venue_type='').count() / total * 100,
        'Compagnie': drinks.exclude(company='').count() / total * 100,
        'Format': drinks.exclude(serving_format='').count() / total * 100,
        'Prix': drinks.filter(price__isnull=False).count() / total * 100,
        'Note': drinks.filter(note__isnull=False).count() / total * 100,
        'Commentaire': drinks.exclude(comment='').count() / total * 100,
        'Photo': drinks.exclude(photo='').exclude(photo__isnull=True).count() / total * 100,
    }


def context_blocks(drinks, prefix):
    """Où on boit, avec qui, dans quel format (donuts) : uniquement les dégustations où le membre l'a indiqué."""
    blocks, notes = [], []
    for key, field, title, labels in (
        ('venue', 'venue_type', 'Où on boit', VENUE_LABELS),
        ('company', 'company', 'Avec qui on boit', COMPANY_LABELS),
        ('format', 'serving_format', 'Format servi', FORMAT_LABELS),
    ):
        rows, hidden = published(drinks, field, lambda value, labels=labels: labels.get(value, value))
        if rows:
            blocks.append(_donut(f'{prefix}-{key}', title, rows, 'Dégustations pour lesquelles le membre l\'a indiqué (information facultative)'))
        notes.append(_hidden_note(hidden, title))
    return blocks + [note for note in notes if note]


def price_stats(drinks):
    """(prix en €, dégustateurs distincts) de chaque dégustation avec un prix, ou None si le groupe est trop petit pour être publié."""
    rows = list(drinks.filter(price__isnull=False).values_list('price', 'drinker', 'serving_format'))
    if not is_publishable(len({drinker for _, drinker, _ in rows})):
        return None
    return [(float(price), drinker, fmt) for price, drinker, fmt in rows]


def price_blocks(drinks, prefix, community_average=None):
    """Prix payé : moyenne, médiane, répartition. `community_average` ajoute un repère de comparaison (brasserie ou bar vs communauté)."""
    prices = price_stats(drinks)
    if prices is None:
        return [Note(f"Pas assez de prix renseignés pour les afficher de façon anonyme (au moins {MIN_GROUP_SIZE} dégustateurs distincts).")]
    values = [price for price, _, _ in prices]
    average = sum(values) / len(values)
    hint = f'{len(values)} prix renseignés'
    if community_average:
        hint += f' · communauté : {euros(community_average)}'
    counts = [sum(1 for value in values if low <= value < high) for low, high, _ in PRICE_BUCKETS]
    return [
        Kpi('Prix moyen payé', euros(average), hint=hint),
        Kpi('Prix médian payé', euros(median(values)), hint='la moitié des verres coûte moins'),
        Chart(f'{prefix}-price-distribution', 'Répartition des prix payés', 'bar', [label for *_x, label in PRICE_BUCKETS],
              [{'name': 'Dégustations', 'data': counts}], subtitle='Prix déclaré par les membres pour le verre bu'),
    ]


def community_average_price(drinks):
    prices = price_stats(drinks)
    return sum(price for price, _, _ in prices) / len(prices) if prices else None


def audience_blocks(drinks, prefix, today):
    """Âge et genre des dégustateurs, en tranches agrégées (donuts) ; les tranches de moins de MIN_GROUP_SIZE membres sont masquées."""
    seg = segments(drinks, today)
    blocks, notes = [], []
    for index, key, title, unknown in ((0, 'age', 'Âge des dégustateurs', None), (1, 'gender', 'Genre des dégustateurs', UNDISCLOSED)):
        counts = defaultdict(int)
        for pair in seg.values():
            if pair[index] and pair[index] != unknown:
                counts[pair[index]] += 1
        order = [label for *_x, label in AGE_BANDS] if index == 0 else list(GENDER_LABELS.values())
        rows = [{'label': label, 'n': counts[label]} for label in order if is_publishable(counts[label])]
        hidden = sum(counts[label] for label in order if not is_publishable(counts[label]))
        if rows:
            blocks.append(_donut(f'{prefix}-{key}', title, rows, 'Dégustateurs distincts ; données d\'inscription, jamais montrées aux autres membres',
                                 name='Dégustateurs'))
        if hidden:
            notes.append(Note(f"{hidden} dégustateur(s) de « {title} » masqué(s) : moins de {MIN_GROUP_SIZE} par catégorie."))
    return blocks + notes


def segment_totals(drinks, seg, index):
    """{segment: {'tastings', 'drinkers', 'note_sum', 'rated'}} (index 0 : tranche d'âge, 1 : genre), segments inconnus exclus."""
    totals = defaultdict(lambda: {'tastings': 0, 'drinkers': set(), 'note_sum': 0, 'rated': 0})
    for row in drinks.values('drinker').annotate(n=Count('pk'), total=Sum('note'), rated=Count('note')):
        segment = seg.get(row['drinker'], (None, UNDISCLOSED))[index]
        if not segment or segment == UNDISCLOSED:
            continue
        entry = totals[segment]
        entry['tastings'] += row['n']
        entry['drinkers'].add(row['drinker'])
        entry['note_sum'] += row['total'] or 0
        entry['rated'] += row['rated']
    return {name: entry for name, entry in totals.items() if is_publishable(len(entry['drinkers']))}


def style_by_segment(drinks, seg, index, chart_id, title, order):
    """Heatmap : part de chaque style dans les dégustations d'un segment (âge ou genre). Une case n'est remplie qu'avec assez de dégustateurs."""
    cells = defaultdict(lambda: [0, set()])
    totals, volume = defaultdict(int), defaultdict(int)
    for row in drinks.values('beer__style', 'drinker').annotate(n=Count('pk')):
        segment = seg.get(row['drinker'], (None, UNDISCLOSED))[index]
        if not segment or segment == UNDISCLOSED:
            continue
        for style in split_styles(row['beer__style']):
            cell = cells[(segment, style)]
            cell[0] += row['n']
            cell[1].add(row['drinker'])
            totals[segment] += row['n']
            volume[style] += row['n']
    drinkers_by_segment = defaultdict(set)
    for (segment, _style), (_n, drinkers) in cells.items():
        drinkers_by_segment[segment] |= drinkers
    segment_names = [name for name in order if is_publishable(len(drinkers_by_segment.get(name, ())))]
    styles = [style for style, _ in sorted(volume.items(), key=lambda item: -item[1])[:HEATMAP_STYLES]]
    if not segment_names or not styles:
        return None
    series = []
    for name in segment_names:
        data = []
        for style in styles:
            count, drinkers = cells.get((name, style), (0, set()))
            data.append(round(count / totals[name] * 100, 1) if count and is_publishable(len(drinkers)) else 0)
        if any(data):
            series.append({'name': name, 'data': data})
    if not series:
        return None
    return Chart(chart_id, title, 'heatmap', styles, series,
                 subtitle=f'Part (%) de chaque style dans les dégustations du segment ; case à 0 : aucune ou moins de {MIN_GROUP_SIZE} dégustateurs')


def average_note(drinks):
    return drinks.aggregate(avg=Avg('note'))['avg']
