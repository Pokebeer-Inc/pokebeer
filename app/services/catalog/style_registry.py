"""Référentiel des styles : ramène la saisie libre aux noms officiels et renseigne la famille de chaque bière.

Les règles sont pures (domain/styles.py) ; ce module ne fait que les alimenter avec la table `Style` (modifiable par l'équipe), gardée en
cache et vidée dès qu'un style change. Branché sur `pre_save` de `Beer` (voir apps.py) : toute écriture d'une bière, quelle que soit sa
provenance (formulaire, modération, suggestion, administration), passe par le même chemin.
"""
from django.core.cache import cache
from django.db.models.signals import post_delete, post_save, pre_save

from ...domain import styles
from ...models import Beer, Style

CACHE_KEY = 'style_registry'
CACHE_SECONDS = 600


def _load():
    canonical_by_key, family_by_name = {}, {}
    for style in Style.objects.all():
        family_by_name[style.name] = style.family
        for written in (style.name, *style.alias_list):
            canonical_by_key[styles.style_key(written)] = style.name
    return canonical_by_key, family_by_name


def registry():
    """({clé -> nom officiel}, {nom officiel -> famille})."""
    return cache.get_or_set(CACHE_KEY, _load, CACHE_SECONDS)


def canonicalize(value):
    """Saisie ramenée aux noms officiels ; un style inconnu est seulement mis en forme."""
    return styles.canonicalize(value, registry()[0])


def family_of(value):
    return styles.family_of(value, registry()[1])


def recognized(value):
    """Vrai si tous les styles du champ sont au référentiel."""
    known = registry()[1]
    return all(style in known for style in styles.split_styles(value))


def _apply(sender, instance, update_fields=None, **kwargs):
    """Avant l'enregistrement d'une bière : style normalisé, famille à jour."""
    if update_fields is not None and 'style' not in update_fields:
        return
    instance.style = canonicalize(instance.style) or instance.style
    instance.style_family = family_of(instance.style)
    if update_fields is not None and instance.pk:
        # Écriture partielle limitée au style : la famille doit suivre sans que l'appelant ait à la connaître
        Beer.objects.filter(pk=instance.pk).update(style_family=instance.style_family)


def renormalize_all():
    """Réapplique le référentiel à toutes les bières (après une modification des alias). Renvoie le nombre de bières modifiées.

    Passe par `bulk_update` : pas de signal, donc pas de recalcul de vecteur ici (voir `manage.py embed_beers`)."""
    cache.delete(CACHE_KEY)
    changed = []
    for beer in Beer.objects.exclude(style__isnull=True).exclude(style='').only('id', 'style', 'style_family'):
        style, family = canonicalize(beer.style), family_of(canonicalize(beer.style))
        if (style, family) != (beer.style, beer.style_family):
            beer.style, beer.style_family = style, family
            changed.append(beer)
    Beer.objects.bulk_update(changed, ['style', 'style_family'], batch_size=500)
    return len(changed)


def forget(**kwargs):
    cache.delete(CACHE_KEY)


def connect_signals():
    pre_save.connect(_apply, sender=Beer, dispatch_uid='normalize_beer_style')
    for signal in (post_save, post_delete):
        signal.connect(forget, sender=Style, dispatch_uid=f'forget_style_registry_{signal is post_save}')
