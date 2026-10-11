"""Abonnés et abonnements d'un membre : comptés en base, affichés par pages (une fenêtre de profil ne charge pas des milliers de lignes)."""
from ...models import UserFollow

FOLLOW_PAGE = 30  # lignes montrées à l'ouverture d'une fenêtre ; la suite arrive par « Charger plus » (10 à la fois)


def followers_of(user):
    return (UserFollow.objects.filter(followed=user, follower__is_active=True)
            .select_related('follower').prefetch_related('follower__socialaccount_set').order_by('-id'))


def following_of(user):
    return (UserFollow.objects.filter(follower=user, followed__is_active=True)
            .select_related('followed').prefetch_related('followed__socialaccount_set').order_by('-id'))


def follow_context(user):
    """Contexte des deux fenêtres : première page de chaque liste, total exact, et s'il en reste à charger."""
    followers, following = followers_of(user), following_of(user)
    followers_count, following_count = followers.count(), following.count()
    return {
        'followers': list(followers[:FOLLOW_PAGE]), 'followers_count': followers_count, 'followers_has_more': followers_count > FOLLOW_PAGE,
        'following': list(following[:FOLLOW_PAGE]), 'following_count': following_count, 'following_has_more': following_count > FOLLOW_PAGE,
        'follow_page': FOLLOW_PAGE,
    }
