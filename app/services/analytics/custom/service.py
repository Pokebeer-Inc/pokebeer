"""Vues et tuiles personnalisées : création, modification, suppression, quotas. La propriété est vérifiée par l'appelant
(`owned_view`), jamais déduite d'un identifiant d'utilisateur reçu du navigateur."""
import re

from django.db import IntegrityError, transaction

from ....models import AnalyticsLayout, AnalyticsTile, AnalyticsView
from ..registry import AnalyticsPage
from . import engine
from .spec import SpecError, normalize_text

MAX_VIEWS = 20
MAX_TILES = 30
NAME_MAX = 80
LAYOUT_KEY = re.compile(r'^custom-(\d+)$')


def page_key(view):
    return f'custom-{view.pk}'


def owned_layout_view(user, key):
    """La vue personnalisée désignée par une clé de disposition « custom-<id> », si elle appartient à l'utilisateur."""
    match = LAYOUT_KEY.match(key)
    return AnalyticsView.objects.filter(pk=int(match.group(1)), user=user).first() if match else None


def clean_name(value):
    name = normalize_text(value)
    if not name:
        raise SpecError("Donnez un nom à la vue.")
    if len(name) > NAME_MAX:
        raise SpecError(f"Le nom est limité à {NAME_MAX} caractères.")
    return name


def create_view(user, name):
    name = clean_name(name)
    if AnalyticsView.objects.filter(user=user).count() >= MAX_VIEWS:
        raise SpecError(f"Vous avez atteint la limite de {MAX_VIEWS} vues.")
    try:
        with transaction.atomic():
            return AnalyticsView.objects.create(user=user, name=name)
    except IntegrityError:
        raise SpecError("Vous avez déjà une vue portant ce nom.") from None


def rename_view(view, name):
    view.name = clean_name(name)
    try:
        with transaction.atomic():
            view.save(update_fields=['name'])
    except IntegrityError:
        raise SpecError("Vous avez déjà une vue portant ce nom.") from None
    return view


def delete_view(view):
    """Supprime la vue, ses tuiles (cascade) et la disposition mémorisée qui lui correspond."""
    AnalyticsLayout.objects.filter(user=view.user, page_key=page_key(view)).delete()
    view.delete()


def add_tile(view, title, spec):
    if view.tiles.count() >= MAX_TILES:
        raise SpecError(f"Une vue est limitée à {MAX_TILES} tuiles.")
    return AnalyticsTile.objects.create(view=view, title=title, spec=spec.to_json())


def update_tile(tile, title, spec):
    tile.title, tile.spec = title, spec.to_json()
    tile.save(update_fields=['title', 'spec'])
    return tile


def build_page(view):
    """Page d'analytics (même modèle que les pages prédéfinies) dont les blocs viennent des tuiles de la vue."""
    tiles = list(view.tiles.all())

    def build(period, params):
        filters = {'brewery': params.get('brewery', '')}
        return [engine.build_block(tile.pk, tile.title, tile.spec, period, filters) for tile in tiles]

    return AnalyticsPage(
        page_key(view), view.name, "Vue personnalisée : mêmes filtres que les autres pages, vos propres tuiles.",
        build, granularity=True, pickers=('brewery',), is_custom=True,
    )
