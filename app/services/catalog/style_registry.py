"""Référentiel des styles : ramène la saisie libre aux noms officiels, structure le champ `style` d'une bière et renseigne sa famille.

Les règles sont pures (domain/styles.py, domain/style_structure.py) ; ce module ne fait que les alimenter avec les tables `Style` et
`StyleFamily` (modifiables par l'équipe), gardées en cache et vidées dès qu'un style change. Branché sur l'enregistrement de `Beer` (voir apps.py) :
toute écriture d'une bière, quelle que soit sa provenance (formulaire, modération, suggestion, administration), passe par le même chemin. Les
écritures en masse (`bulk_create`, `update`) contournent les signaux : elles appellent `rebuild_all` ou `rebuild`.
"""
from django.core.cache import cache
from django.db.models.signals import post_delete, post_save, pre_save

from ...domain import style_structure, styles
from ...models import Beer, BeerStyle, Style
from . import styles as catalog_styles

CACHE_KEY = 'style_registry'
CACHE_SECONDS = 600
MODELS = style_structure.Models(Style, BeerStyle, Beer)
SUGGESTIONS = 8
_UNKNOWN = object()  # bière jamais lue depuis la base : on ne sait pas si son style a changé


def _load():
    canonical_by_key, family_by_name = {}, {}
    for style in Style.objects.filter(is_official=True).select_related('family'):
        family_by_name[style.name] = style.family.name
        for written in (style.name, *style.alias_list):
            canonical_by_key[styles.style_key(written)] = style.name
    return canonical_by_key, family_by_name


def registry():
    """({clé -> nom officiel}, {nom officiel -> famille}), pour les seuls styles officiels."""
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


def suggest(term, limit=SUGGESTIONS):
    """Styles officiels dont le nom ou un alias contient la saisie : [{'name', 'family'}] (sans requête). Dans l'ordre : le nom commence par la
    saisie, puis un alias, puis elle n'apparaît qu'au milieu."""
    key = styles.style_key(term)
    if not key:
        return []
    canonical_by_key, family_by_name = registry()
    ranked = {}
    for written, name in canonical_by_key.items():
        if key in written:
            rank = 2 if not written.startswith(key) else (0 if written == styles.style_key(name) else 1)
            ranked[name] = min(ranked.get(name, rank), rank)
    return [{'name': name, 'family': family_by_name[name]} for name in sorted(ranked, key=lambda name: (ranked[name], name))[:limit]]


def rebuild(beers):
    """Remet à jour les styles liés de ces bières (texte normalisé, style principal). Renvoie le nombre de bières modifiées."""
    changed = style_structure.rebuild(beers, MODELS, style_structure.Registry(Style.objects.all()))
    catalog_styles.forget()
    return changed


def rebuild_all():
    """Réapplique le référentiel à toutes les bières (après une modification des alias, ou une écriture en masse). Renvoie le nombre de bières
    modifiées. Les styles « à valider » devenus inutiles (plus aucune bière) sont supprimés.

    Passe par `bulk_update` : pas de signal, donc pas de recalcul de vecteur ici (voir `manage.py embed_beers`)."""
    cache.delete(CACHE_KEY)
    changed = rebuild(Beer.objects.exclude(style__isnull=True).exclude(style=''))
    Style.objects.filter(is_official=False, beer_styles__isnull=True).delete()
    return changed


renormalize_all = rebuild_all  # nom historique (action de l'administration, commande normalize_styles)


def _normalize(sender, instance, update_fields=None, **kwargs):
    """Avant l'enregistrement d'une bière : texte du style ramené aux noms officiels."""
    if update_fields is None or 'style' in update_fields:
        instance.style = canonicalize(instance.style) or instance.style


def _structure(sender, instance, created, update_fields=None, **kwargs):
    """Après l'enregistrement : styles liés et style principal, seulement quand le texte du style a changé (ou à la création)."""
    if update_fields is not None and 'style' not in update_fields:
        return
    if created:
        if not instance.style:
            return
    elif getattr(instance, '_loaded_style', _UNKNOWN) == instance.style:
        return
    rebuild([instance])
    instance._loaded_style = instance.style


def forget(**kwargs):
    cache.delete(CACHE_KEY)
    catalog_styles.forget()


def connect_signals():
    pre_save.connect(_normalize, sender=Beer, dispatch_uid='normalize_beer_style')
    post_save.connect(_structure, sender=Beer, dispatch_uid='structure_beer_style')
    for signal in (post_save, post_delete):
        signal.connect(forget, sender=Style, dispatch_uid=f'forget_style_registry_{signal is post_save}')
