"""Droits sur une fiche de bière : la seule source de ces règles (pages, modération, gabarits).

- Modifier ou retirer : le gérant de la brasserie, ou le créateur tant que la fiche n'a pas été vérifiée par l'équipe.
- Voir une bière retirée du catalogue : ses gérants et les membres qui l'ont dégustée (leur avis reste consultable), personne d'autre.
"""
from ..establishments.team import is_manager


def is_brewery_manager(user, beer):
    return bool(beer.brewery_id) and is_manager(user, beer.brewery)


def can_edit(user, beer):
    if not user.is_authenticated:
        return False
    return is_brewery_manager(user, beer) or (beer.added_by_id == user.pk and not beer.is_verified)


# Retirer une bière du catalogue suit exactement la règle de modification
can_delete = can_edit


def can_view(user, beer):
    if not beer.is_deleted:
        return True
    if not user.is_authenticated:
        return False
    return is_brewery_manager(user, beer) or beer.drinks_set.filter(drinker=user).exists()
