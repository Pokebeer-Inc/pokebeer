"""Relations entre membres : abonnements et blocages. Les vues valident la demande ; les règles (blocages, notifications) sont ici."""
from ...models import UserBlock, UserFollow
from ..messaging.notifications import notify
from .achievements import check_and_notify_achievements
from .blocks import invite_blockers_to_report
from .visibility import is_blocked_between


class Unreachable(Exception):
    """Membre avec qui un blocage existe : on répond comme pour un profil inexistant."""


def toggle_follow(user, target):
    """S'abonne à `target`, ou se désabonne s'il est déjà suivi ; renvoie True si `user` le suit désormais."""
    if is_blocked_between(user, target):
        raise Unreachable
    if user == target:
        return False
    deleted, _ = UserFollow.objects.filter(follower=user, followed=target).delete()
    following = not deleted
    if following:
        UserFollow.objects.get_or_create(follower=user, followed=target)
        notify('follow', [target], sender=user)
    check_and_notify_achievements(user)
    return following


def remove_follower(user, follower):
    """Retire `follower` des abonnés de `user` ; renvoie True s'il le suivait."""
    deleted, _ = UserFollow.objects.filter(follower=follower, followed=user).delete()
    return bool(deleted)


def block(user, target):
    """Bloque `target` : les abonnements dans les deux sens disparaissent ; au-delà d'un seuil de blocages, les bloqueurs sont invités à signaler."""
    if user == target:
        return False
    UserBlock.objects.get_or_create(blocker=user, blocked=target)
    UserFollow.objects.filter(follower=user, followed=target).delete()
    UserFollow.objects.filter(follower=target, followed=user).delete()
    invite_blockers_to_report(target)
    return True


def unblock(user, target):
    UserBlock.objects.filter(blocker=user, blocked=target).delete()
