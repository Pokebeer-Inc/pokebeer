"""Lieux posés sur la carte par les membres : création, modification, qui est invité et qui est prévenu."""
from django.db import transaction
from django.db.models import Q

from ...models import BeerSpot, BeerUser, Drinks
from ..common.images import delete_stored_file
from ..members.achievements import check_and_notify_achievements
from ..messaging.notifications import notify
from ..members.visibility import exclude_blocked


def participant_drinks(spot, drink_slugs):
    """Restreint les dégustations à celles du créateur du lieu et de ses amis invités."""
    participants = Q(drinker=spot.user) | Q(drinker__in=spot.friends.all())
    return Drinks.objects.filter(participants, slug__in=drink_slugs)


def invitable_friends(user, usernames):
    """Ne garde que les comptes actifs, sans blocage avec `user`, parmi les amis invités (désignés par leur pseudo) ; renvoie leurs clés internes."""
    return list(exclude_blocked(BeerUser.objects.filter(username__in=usernames, is_active=True), user, 'id').exclude(id=user.id).values_list('id', flat=True))


def can_edit(spot, user):
    """Le créateur du lieu et ses amis invités peuvent le modifier."""
    return spot.user_id == user.pk or spot.friends.filter(pk=user.pk).exists()


def create_spot(user, fields, drink_slugs, friend_ids):
    """Crée le lieu, invite les amis (ils sont prévenus) et y rattache les dégustations."""
    spot = BeerSpot.objects.create(user=user, **fields)
    if friend_ids:
        spot.friends.set(friend_ids)
        notify('spot_invite', friend_ids, sender=user, spot=spot)
    if drink_slugs:
        spot.drinks.set(participant_drinks(spot, drink_slugs))
    check_and_notify_achievements(user)
    return spot


def update_spot(spot, editor, fields, drink_slugs, friend_ids):
    """Modifie le lieu. L'éditeur remplace SES dégustations rattachées (sans doublon de bière avec celles des autres) ; seul le créateur gère
    la liste des amis. Les nouveaux amis reçoivent l'invitation, les autres membres concernés une notification de mise à jour.
    `fields['photo']` : le nouveau fichier, ou None pour retirer la photo ; absent, la photo reste. L'ancien fichier est effacé une fois
    la modification validée."""
    previous = spot.photo
    previous_file = (previous.storage, previous.name) if previous and 'photo' in fields else None
    for name, value in fields.items():
        setattr(spot, name, value)
    spot.save()
    if previous_file:
        transaction.on_commit(lambda: delete_stored_file(*previous_file))

    editor_drinks = spot.drinks.filter(drinker=editor)
    spot.drinks.remove(*editor_drinks)
    if drink_slugs:
        # On identifie les bières déjà ajoutées par les autres sur ce point, puis on ne garde que les dégustations dont la bière n'y est pas déjà
        beers_from_others = spot.drinks.exclude(drinker=editor).values_list('beer', flat=True)
        spot.drinks.add(*participant_drinks(spot, drink_slugs).exclude(beer__in=beers_from_others))

    new_friends = []
    if editor == spot.user:
        old_friends = set(spot.friends.values_list('id', flat=True))
        spot.friends.set(friend_ids)
        new_friends = [pk for pk in spot.friends.values_list('id', flat=True) if pk not in old_friends]
        notify('spot_invite', new_friends, sender=editor, spot=spot)

    # Le créateur et les amis du lieu, sauf celui qui agit (pas d'auto-notification) et les amis tout juste invités (déjà prévenus)
    to_notify = set(spot.friends.values_list('id', flat=True)) | {spot.user.id}
    to_notify -= {editor.id, *new_friends}
    notify('spot_updated', to_notify, sender=editor, spot=spot)
    check_and_notify_achievements(editor)
