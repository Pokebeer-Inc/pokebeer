"""Suppression d'une dégustation : règle partagée entre l'utilisateur (sa note) et la modération (son avis)."""


def clear_top_beer_slots(user, beer):
    """Retire la bière du Top 3 de l'utilisateur si elle y figure."""
    updated = False
    for slot in ('top_beer_1', 'top_beer_2', 'top_beer_3'):
        if getattr(user, slot) == beer:
            setattr(user, slot, None)
            updated = True
    if updated:
        user.save()


def delete_drink(drink):
    clear_top_beer_slots(drink.drinker_id, drink.beer_id)
    drink.delete()
