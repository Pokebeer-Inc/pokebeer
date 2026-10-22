"""Structure d'un champ `style` : « IPA, Stout » devient deux styles liés à la bière, dans l'ordre, dont un style principal (le premier reconnu).

Une seule écriture pour tout le monde : le service en ligne (services/catalog/style_registry.py) et les migrations de données l'appellent avec
leurs propres classes de modèles (réelles ou historiques), d'où le paramètre `models`. Aucune règle n'est dupliquée.

Un style absent du référentiel n'est pas perdu : il devient un style « à valider » (non officiel, sans famille) que l'équipe rattache ensuite."""
from collections import defaultdict, namedtuple

from . import styles as rules

Models = namedtuple('Models', 'Style BeerStyle Beer')

MAX_STYLES = 3          # une bière en mélange au plus trois styles : au-delà, ce n'est plus un style
MAX_LABEL_LENGTH = 100  # taille de Beer.style


class Registry:
    """Les styles de la base : `canonical_by_key` ne contient que les styles officiels (noms et alias), `by_name` les contient tous."""

    def __init__(self, style_rows):
        self.by_name, self.canonical_by_key = {}, {}
        for style in style_rows:
            self.by_name[style.name] = style
            if style.is_official:
                for written in (style.name, *rules.alias_lines(style.aliases)):
                    self.canonical_by_key[rules.style_key(written)] = style.name

    def style(self, name, models):
        """Le style de ce nom, créé « à valider » s'il n'existe pas encore."""
        if name not in self.by_name:
            self.by_name[name] = models.Style.objects.get_or_create(name=name, defaults={'is_official': False})[0]  # deux envois simultanés : un seul style
        return self.by_name[name]


def labels(text, registry):
    """Noms officiels (ou mis en forme, pour un style inconnu) d'un champ, dans l'ordre, au plus MAX_STYLES et MAX_LABEL_LENGTH caractères."""
    kept, length = [], 0
    for name in rules.split_styles(rules.canonicalize(text, registry.canonical_by_key))[:MAX_STYLES]:
        length += len(name) + (2 if kept else 0)
        if length > MAX_LABEL_LENGTH:
            break
        kept.append(name)
    return kept


def _primary(styles):
    """Premier style officiel, sinon le premier : sa famille (ou son absence) fait foi dans les statistiques."""
    return next((style for style in styles if style.is_official), styles[0] if styles else None)


def rebuild(beers, models, registry):
    """Remet à jour les styles liés, le style principal et le texte normalisé de ces bières. Renvoie le nombre de bières modifiées.

    Trois requêtes pour tout le lot (relecture des liens, suppression, création) plus une mise à jour des bières modifiées."""
    beers = list(beers)
    existing = defaultdict(list)
    for beer_id, style_id in models.BeerStyle.objects.filter(beer__in=beers).order_by('position').values_list('beer_id', 'style_id'):
        existing[beer_id].append(style_id)

    new_rows, touched, changed = [], [], 0
    for beer in beers:
        styles = [registry.style(name, models) for name in labels(beer.style, registry)]
        primary = _primary(styles)
        label = ', '.join(style.name for style in styles) or beer.style
        ids = [style.pk for style in styles]
        if ids == existing[beer.pk] and (label, beer.primary_style_id) == (beer.style, getattr(primary, 'pk', None)):
            continue
        changed += 1
        touched.append(beer.pk)
        new_rows += [models.BeerStyle(beer_id=beer.pk, style=style, position=position) for position, style in enumerate(styles)]
        beer.style, beer.primary_style = label, primary

    if touched:
        models.BeerStyle.objects.filter(beer_id__in=touched).delete()
        models.BeerStyle.objects.bulk_create(new_rows)
        touched = set(touched)
        models.Beer.objects.bulk_update([beer for beer in beers if beer.pk in touched], ['style', 'primary_style'], batch_size=500)
    return changed
