from ..models import UserBlock

def get_excluded_users(user):
    """Retourne la liste des IDs d'utilisateurs avec qui il y a un blocage."""
    if not user.is_authenticated: return []
    blocked_by_me = UserBlock.objects.filter(blocker=user).values_list('blocked_id', flat=True)
    blocking_me = UserBlock.objects.filter(blocked=user).values_list('blocker_id', flat=True)
    return list(set(blocked_by_me) | set(blocking_me))