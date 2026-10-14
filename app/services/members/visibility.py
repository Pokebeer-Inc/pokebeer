"""Qui peut voir quoi : blocages entre membres et comptes suspendus, appliqués à une requête par sous-requête SQL (aucun identifiant chargé en mémoire)."""
from django.db.models import Q

from ...models import UserBlock


def _blocked_q(user, field):
    """Condition « `field` désigne un membre avec qui `user` a un blocage, dans un sens ou dans l'autre » (sous-requêtes, rien en mémoire)."""
    return (Q(**{f'{field}__in': UserBlock.objects.filter(blocker=user).values('blocked_id')})
            | Q(**{f'{field}__in': UserBlock.objects.filter(blocked=user).values('blocker_id')}))


def exclude_blocked(queryset, user, field):
    """Retire les lignes dont `field` est un membre bloqué (ou qui a bloqué `user`) : une seule requête, aucun identifiant chargé."""
    if not user.is_authenticated:
        return queryset
    return queryset.exclude(_blocked_q(user, field))


def exclude_hidden_users(queryset, user, field):
    """Comme `exclude_blocked`, et retire aussi les comptes suspendus."""
    queryset = queryset.exclude(**{f'{field}__is_active': False})
    return exclude_blocked(queryset, user, field)


def is_blocked_between(user, other):
    """Vrai s'il existe un blocage entre ces deux membres, dans un sens ou dans l'autre."""
    return user.is_authenticated and user.is_blocked_with(other)
