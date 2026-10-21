"""Carte d'un bar : les bières qu'il sert (voir models/menus.py).

Un seul endroit décide des droits (`can_manage`), des limites et des règles ; les vues ne font que valider les formulaires et répondre.
Ajouter une bière déjà servie met à jour sa ligne (jamais de doublon) ; retirer une bière garde la ligne (historique, analytics).
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from ...models import Bar, BarBeer
from ..catalog import selectors
from .team import is_manager

MAX_ACTIVE_ENTRIES = 300  # une carte réaliste en compte quelques dizaines : au-delà, c'est un abus ou une erreur


class MenuError(Exception):
    """Refus affichable au gérant."""


def can_manage(user, bar):
    """Les gérants du bar et l'équipe peuvent modifier la carte."""
    return user.is_authenticated and user.is_active and (user.is_staff or user.is_superuser or is_manager(user, bar))


def entries(bar):
    """Lignes en cours de la carte, par nom de bière."""
    return BarBeer.objects.active().filter(bar=bar).select_related('beer__brewery').order_by('beer__name')


def ensure_room(bar):
    """Lève MenuError si la carte est pleine (à vérifier avant de créer une bière qu'on voudrait y ajouter)."""
    if BarBeer.objects.filter(bar=bar, removed_at__isnull=True).count() >= MAX_ACTIVE_ENTRIES:
        raise MenuError(f"La carte est pleine ({MAX_ACTIVE_ENTRIES} bières au plus).")


def add(bar, beer, user, price=None, serving_format=''):
    """Ajoute la bière à la carte, ou met à jour sa ligne si elle y est déjà. Renvoie (ligne, créée). Lève MenuError si la bière n'est plus
    au catalogue ou si la carte est pleine."""
    if beer.is_deleted:
        raise MenuError("Cette bière n'est plus au catalogue.")
    try:
        with transaction.atomic():
            current = BarBeer.objects.select_for_update().filter(bar=bar, beer=beer, removed_at__isnull=True).first()
            if current:
                # Rajouter une bière déjà servie ne doit pas effacer son prix : seules les valeurs données remplacent les anciennes
                return update(current, price if price is not None else current.price, serving_format or current.serving_format), False
            ensure_room(bar)
            return BarBeer.objects.create(bar=bar, beer=beer, price=price, serving_format=serving_format, added_by=user), True
    except IntegrityError:
        # Deux ajouts simultanés : l'autre a créé la ligne entre-temps, on la met à jour
        current = BarBeer.objects.get(bar=bar, beer=beer, removed_at__isnull=True)
        return update(current, price, serving_format), False


def update(entry, price, serving_format):
    entry.price, entry.serving_format = price, serving_format
    entry.save(update_fields=['price', 'serving_format'])
    return entry


def remove(entry):
    """Retire la bière de la carte (la ligne est conservée avec sa date de retrait)."""
    if entry.removed_at is None:
        entry.removed_at = timezone.now()
        entry.save(update_fields=['removed_at'])
    return entry


def candidates(user, bar, term):
    """Bières proposées par la recherche du sélecteur, chacune marquée `on_menu` si le bar la sert déjà."""
    found = selectors.find_beers_to_pick(user, term)
    served = set(entries(bar).filter(beer__in=found).values_list('beer_id', flat=True))
    return [{'beer': beer, 'on_menu': beer.pk in served} for beer in found]


SERVING_BARS_SHOWN = 6


def serving_bars(beer):
    """(nombre de bars qui servent la bière, quelques-uns à afficher) : « Servie dans N bars » sur la fiche d'une bière."""
    bars = Bar.objects.filter(menu_entries__beer=beer, menu_entries__removed_at__isnull=True).distinct().order_by('name')
    return {'count': bars.count(), 'bars': list(bars[:SERVING_BARS_SHOWN])}
