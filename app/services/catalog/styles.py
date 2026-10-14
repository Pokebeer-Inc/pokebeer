"""Styles du catalogue (filtres de recherche) : calculés une fois puis gardés en cache, vidé dès qu'une bière change (connect_signals)."""
from django.core.cache import cache
from django.db.models.signals import post_delete, post_save

from ...domain.styles import distinct_styles
from ...models import Beer

CACHE_KEY = 'beer_styles'
CACHE_SECONDS = 600


def catalog_styles():
    """Styles des bières du catalogue, triés (la liste ne change qu'avec le catalogue : la relire à chaque recherche parcourait toute la colonne)."""
    def compute():
        return distinct_styles(Beer.objects.filter(is_deleted=False).exclude(style__isnull=True).exclude(style='')
                               .values_list('style', flat=True).distinct())
    return cache.get_or_set(CACHE_KEY, compute, CACHE_SECONDS)


def styles_in(drinks):
    """Styles présents dans ces dégustations (queryset), triés."""
    return distinct_styles(drinks.exclude(beer__style__isnull=True).exclude(beer__style='').values_list('beer__style', flat=True).distinct())


def forget(**kwargs):
    cache.delete(CACHE_KEY)


def connect_signals():
    for signal in (post_save, post_delete):
        signal.connect(forget, sender=Beer, dispatch_uid=f'forget_beer_styles_{signal is post_save}')
