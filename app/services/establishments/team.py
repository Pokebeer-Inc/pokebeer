"""Équipe d'un établissement (brasserie ou bar) : qui la gère, invitations et retraits.

Un gérant n'ajoute plus directement un membre : il l'invite, et le rôle de gérant (groupe Brasseur ou Bartender, donné par le signal des
gérants) n'est accordé qu'une fois l'invitation acceptée. Une invitation n'est valable que pendant INVITATION_VALIDITY, et seulement si la
personne qui l'a envoyée gère toujours l'établissement. Retirer un gérant lui retire le rôle, sauf s'il gère un autre établissement du même type.
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from ...models import BeerUser, Brewery, ManagerInvitation, Notification
from ..catalog import search
from ..members.visibility import exclude_blocked
from ..messaging.notifications import notify
from ..protection.throttle import TEAM_INVITE_BY_USER

INVITATION_VALIDITY = timedelta(days=30)
SEARCH_LIMIT = 10
INVITED_NOTIFICATION = 'manager_invited'

Status = ManagerInvitation.Status


class TeamError(Exception):
    """Action refusée : le message est affichable tel quel."""


def is_manager(user, place):
    return user.is_authenticated and place.managers.filter(pk=user.pk).exists()


def _place_ref(place):
    """{'brewery': place} ou {'bar': place} : champ de l'établissement dans ManagerInvitation et Notification."""
    return {'brewery' if isinstance(place, Brewery) else 'bar': place}


def _pending(**filters):
    return ManagerInvitation.objects.filter(status=Status.PENDING, created_at__gte=timezone.now() - INVITATION_VALIDITY, **filters)


def invitations_for(user):
    """Invitations en attente adressées à ce membre (page Profil)."""
    return _pending(invitee=user).select_related('brewery', 'bar', 'invited_by')


def invitations_of(place):
    """Invitations en attente pour cet établissement (fenêtre de gestion de l'équipe)."""
    return _pending(**_place_ref(place)).select_related('invitee')


def invitable_members(place, inviter, query=''):
    """Membres qu'on peut inviter : actifs, ni gérants, ni déjà invités, sans blocage avec la personne qui invite."""
    members = BeerUser.objects.filter(is_active=True).exclude(pk=inviter.pk).exclude(pk__in=place.managers.values('pk'))
    members = members.exclude(pk__in=invitations_of(place).values('invitee'))
    members = search.members(members, query) if query else members
    return exclude_blocked(members, inviter, 'id')


def search_invitable(place, inviter, query):
    return list(invitable_members(place, inviter, query).prefetch_related('socialaccount_set').order_by(search.RANK_FIELD, 'username')[:SEARCH_LIMIT])


def _require_manager(place, user):
    if not is_manager(user, place):
        raise TeamError("Vous n'avez pas l'autorisation de gérer l'équipe de cet établissement.")


def invite(place, inviter, username):
    """Invite le membre `username` ; le notifie. Lève TeamError (membre introuvable ou déjà invité, plafond atteint, pas gérant)."""
    _require_manager(place, inviter)
    invitee = invitable_members(place, inviter).filter(username=username or '').first()
    if invitee is None:
        raise TeamError("Ce membre ne peut pas être invité (introuvable, déjà dans l'équipe ou déjà invité).")
    if not TEAM_INVITE_BY_USER.hit(inviter.pk):
        raise TeamError("Trop d'invitations aujourd'hui, réessayez demain.")
    try:
        with transaction.atomic():
            invitation = ManagerInvitation.objects.create(invitee=invitee, invited_by=inviter, **_place_ref(place))
    except IntegrityError:  # invitation en attente créée entre-temps (double envoi)
        TEAM_INVITE_BY_USER.release(inviter.pk)
        raise TeamError("Ce membre a déjà une invitation en attente.") from None
    notify(INVITED_NOTIFICATION, [invitee], sender=inviter, **_place_ref(place))
    return invitation


def _clear_invitation_notice(invitation):
    """L'invitation n'attend plus de réponse : sa notification ne doit plus inviter à agir."""
    Notification.objects.filter(recipient=invitation.invitee_id, notif_type=INVITED_NOTIFICATION, **_place_ref(invitation.place)).delete()


def cancel(invitation, by):
    """Un gérant retire une invitation en attente."""
    _require_manager(invitation.place, by)
    if ManagerInvitation.objects.filter(pk=invitation.pk, status=Status.PENDING).update(status=Status.CANCELLED, responded_at=timezone.now()):
        _clear_invitation_notice(invitation)


def respond(invitation_slug, user, accept):
    """Réponse du membre invité. Accepter l'ajoute aux gérants (le rôle suit) ; la personne qui a invité est prévenue.

    Lève TeamError si l'invitation n'est plus valable (expirée, déjà traitée, ou la personne qui l'a envoyée ne gère plus l'établissement)."""
    with transaction.atomic():
        invitation = (_pending(invitee=user, slug=invitation_slug).select_related('brewery', 'bar', 'invited_by')
                      .select_for_update(of=('self',)).first())
        if invitation is None:
            raise TeamError("Cette invitation n'est plus valable.")
        place, inviter = invitation.place, invitation.invited_by
        inviter_still_manager = inviter is not None and inviter.is_active and is_manager(inviter, place)
        if accept and not inviter_still_manager:
            invitation.status = Status.CANCELLED
        else:
            invitation.status = Status.ACCEPTED if accept else Status.DECLINED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=['status', 'responded_at'])
        if invitation.status == Status.ACCEPTED:
            place.managers.add(user)
    _clear_invitation_notice(invitation)
    if invitation.status == Status.CANCELLED:
        raise TeamError("Cette invitation n'est plus valable : la personne qui l'a envoyée ne gère plus cet établissement.")
    if inviter_still_manager:
        notify('manager_invitation_accepted' if accept else 'manager_invitation_declined', [inviter], sender=user, **_place_ref(place))
    return invitation


def update_place(place_form, editor):
    """Enregistre la fiche modifiée par un gérant (formulaire validé) ; le reste de l'équipe est prévenu."""
    place = place_form.save()
    notify('place_updated', place.managers.exclude(pk=editor.pk), sender=editor, **_place_ref(place))
    return place


def remove_manager(place, by, username):
    """Retire un gérant de l'équipe (jamais soi-même) et le prévient. Renvoie le membre retiré, ou None."""
    _require_manager(place, by)
    if by.username == username:
        return None
    removed = place.managers.filter(username=username).first()
    if removed is None:
        return None
    place.managers.remove(removed)  # le signal retire le rôle s'il ne gère plus aucun établissement de ce type
    notify('manager_removed', [removed], sender=by, text_content=place.name)
    return removed
