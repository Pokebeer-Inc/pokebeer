"""Pouces sur les avis et liste « À goûter » : un clic bascule l'état, les notifications et trophées qui en découlent sont décidés ici."""
from django.db import transaction
from django.db.models import Count, Q

from ...models import DrinkReaction
from ..members.achievements import check_and_notify_achievements
from ..messaging.notifications import notify


class OwnReview(Exception):
    """Un membre ne réagit pas à son propre avis."""


def toggle_reaction(user, drink, is_like):
    """Pouce en l'air (`is_like`) ou en bas : un même clic deux fois annule, l'autre bouton change d'avis. Renvoie la réaction en cours
    (True, False ou None) et les compteurs de l'avis. L'auteur n'est prévenu que d'un pouce en l'air."""
    if drink.drinker_id == user.pk:
        raise OwnReview
    with transaction.atomic():
        reaction, created = DrinkReaction.objects.select_for_update().get_or_create(user=user, drink=drink, defaults={'is_like': is_like})
        if created:
            current = is_like
        elif reaction.is_like == is_like:
            reaction.delete()
            current = None
        else:
            reaction.is_like = is_like
            reaction.save(update_fields=['is_like'])
            current = is_like
    if current:
        notify('drink_liked', [drink.drinker], sender=user, beer=drink.beer)
    check_and_notify_achievements(user)
    counts = drink.reactions.aggregate(likes=Count('id', filter=Q(is_like=True)), dislikes=Count('id', filter=Q(is_like=False)))
    return current, counts


def toggle_wishlist(user, beer, can_add):
    """Ajoute la bière à la liste « À goûter » ou l'en retire ; renvoie True si elle y est désormais. `can_add` : la bière est visible
    du membre (au catalogue, sans blocage). Le créateur de la bière est prévenu d'un ajout."""
    if user.wishlist_beers.filter(pk=beer.pk).exists():
        user.wishlist_beers.remove(beer)  # retirer reste toujours possible
        return False
    if not can_add:
        raise PermissionError("Bière indisponible")
    user.wishlist_beers.add(beer)
    if beer.added_by_id and beer.added_by_id != user.pk:
        notify('wishlist_added', [beer.added_by], sender=user, beer=beer)
    return True
