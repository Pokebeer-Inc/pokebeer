"""Dégustations : notation d'une bière, modification, suppression (règle partagée avec la modération)."""
from django.db import IntegrityError, transaction

from ...models import Drinks
from ..members.achievements import check_and_notify_achievements
from ..messaging.notifications import notify


class AlreadyRated(Exception):
    """Le membre a déjà noté cette bière (deux envois simultanés : la contrainte d'unicité a gardé le premier)."""


def rate(user, beer, drink, notebooks=()):
    """Enregistre la dégustation (instance non sauvegardée d'un formulaire validé), la range dans les carnets choisis, retire la bière de
    la liste « À goûter » et prévient les autres membres qui l'ont dégustée."""
    drink.drinker, drink.beer = user, beer
    try:
        with transaction.atomic():
            drink.save()
    except IntegrityError:
        raise AlreadyRated from None
    drink.notebooks.add(*notebooks)
    user.wishlist_beers.remove(beer)  # sans effet si elle n'y était pas
    others = Drinks.objects.filter(beer=beer).exclude(drinker=user).values_list('drinker', flat=True).distinct()
    notify('beer_shared', others, sender=user, beer=beer)
    check_and_notify_achievements(user)
    return drink


def update(drink_form, user, notebooks=()):
    """Enregistre la modification (formulaire validé) ; la dégustation n'est plus que dans les carnets choisis."""
    drink = drink_form.save()
    drink.notebooks.remove(*user.custom_notebooks.all())
    drink.notebooks.add(*notebooks)
    check_and_notify_achievements(user)
    return drink


def clear_top_beer_slots(user, beer):
    """Retire la bière du Top 3 de l'utilisateur si elle y figure."""
    slots = [slot for slot in ('top_beer_1', 'top_beer_2', 'top_beer_3') if getattr(user, f'{slot}_id') == beer.pk]
    for slot in slots:
        setattr(user, slot, None)
    if slots:
        user.save(update_fields=slots)


def delete_drink(drink):
    clear_top_beer_slots(drink.drinker, drink.beer)
    drink.delete()


def delete_own(drink):
    """Le membre supprime sa propre dégustation (ses trophées suivent)."""
    delete_drink(drink)
    check_and_notify_achievements(drink.drinker)
