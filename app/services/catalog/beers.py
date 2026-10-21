"""Cycle de vie d'une bière du catalogue : ajout (avec la première dégustation), modification, retrait. Les vues ne font que valider les
formulaires et répondre ; les enregistrements, notifications et trophées qui en découlent sont décidés ici."""
from django.db import IntegrityError, transaction

from ...models import BeerDraft, Drinks, Notification, UserFollow
from ..members.achievements import check_and_notify_achievements
from ..messaging.notifications import notify
from .permissions import is_brewery_manager


class NameTaken(Exception):
    """La brasserie a reçu une bière de ce nom entre la validation et l'enregistrement (deux ajouts simultanés)."""


def _announce(user, beer):
    """Ce qui suit la création d'une bière, quelle que soit la voie : abonnés et gérants de la brasserie prévenus, trophées, brouillon effacé."""
    notify('beer_added', UserFollow.objects.filter(followed=user).values_list('follower_id', flat=True), sender=user, beer=beer)
    # La politique d'envoi écarte l'auteur s'il gère lui-même la brasserie
    notify('beer_added_to_brewery', beer.brewery.managers.all(), sender=user, beer=beer)
    check_and_notify_achievements(user)
    BeerDraft.objects.filter(user=user).delete()  # la bière existe : le brouillon n'a plus lieu d'être


def add_beer(user, beer_form, drink_form, notebooks=()):
    """Enregistre la bière et la première dégustation du membre ensemble (formulaires déjà validés), puis prévient ses abonnés et les
    gérants de la brasserie. Lève NameTaken si la contrainte d'unicité refuse la bière (la base a le dernier mot)."""
    try:
        with transaction.atomic():
            beer = beer_form.save(user=user)
            drink = drink_form.save(commit=False)
            drink.drinker, drink.beer = user, beer
            drink.save()
    except IntegrityError:
        beer_form.instance.pk = None
        raise NameTaken from None
    drink.notebooks.add(*notebooks)
    _announce(user, beer)
    return beer


def create_beer(user, beer_form):
    """Enregistre une bière SANS dégustation (formulaire déjà validé) : voie des gérants de bar qui ajoutent à leur carte une bière
    absente du catalogue. Mêmes notifications et mêmes règles que `add_beer`."""
    try:
        with transaction.atomic():
            beer = beer_form.save(user=user)
    except IntegrityError:
        beer_form.instance.pk = None
        raise NameTaken from None
    _announce(user, beer)
    return beer


def _edited_by_manager_for_creator(beer, editor):
    """Le créateur de la fiche doit être prévenu quand un gérant de la brasserie (et non lui-même) y touche."""
    return beer.added_by_id and beer.added_by_id != editor.pk and is_brewery_manager(editor, beer)


def update_beer(beer_form, editor):
    """Enregistre la modification (formulaire validé) et prévient les membres qui l'ont dégustée, et son créateur si c'est un gérant."""
    beer = beer_form.instance
    notify_creator = _edited_by_manager_for_creator(beer, editor)
    beer = beer_form.save()
    drinkers = Drinks.objects.filter(beer=beer).exclude(drinker=editor).values_list('drinker', flat=True).distinct()
    notify('beer_updated', drinkers, sender=editor, beer=beer)
    if notify_creator:
        notify('beer_updated_by_manager', [beer.added_by], sender=editor, beer=beer)
    return beer


def retire_beer(beer, by):
    """Retire la bière du catalogue (les dégustations restent) ; ses notifications disparaissent, le créateur est prévenu par un gérant."""
    notify_creator = _edited_by_manager_for_creator(beer, by)
    beer.is_deleted = True
    beer.save(update_fields=['is_deleted'])
    Notification.objects.filter(beer=beer).delete()
    if beer.added_by:
        check_and_notify_achievements(beer.added_by)
        if notify_creator:
            # Texte libre : la bière n'est plus consultable
            notify('beer_deleted_by_manager', [beer.added_by], sender=by, text_content=beer.name)
