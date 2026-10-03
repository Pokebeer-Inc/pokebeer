"""Anonymat : on n'affiche jamais un groupe assez petit pour identifier un membre (k-anonymat)."""

MIN_GROUP_SIZE = 3


def is_publishable(distinct_members):
    return distinct_members >= MIN_GROUP_SIZE


def group_publishable(points, label_of):
    """Regroupe des lieux par libellé ; un groupe de moins de MIN_GROUP_SIZE membres distincts n'est pas publié.

    Renvoie ([(libellé, lieux, membres)] triés par volume décroissant, nombre de lieux masqués).
    """
    groups = {}
    for point in points:
        label = label_of(point)
        if not label:
            continue
        entry = groups.setdefault(label, {'spots': 0, 'members': set()})
        entry['spots'] += 1
        entry['members'].add(point.user_id)
    rows = [(label, e['spots'], len(e['members'])) for label, e in groups.items() if is_publishable(len(e['members']))]
    hidden = sum(e['spots'] for label, e in groups.items() if not is_publishable(len(e['members'])))
    return sorted(rows, key=lambda r: (-r[1], r[0])), hidden
