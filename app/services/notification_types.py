"""Registre des types de notifications : source unique de vérité.

Chaque type déclare son libellé, sa catégorie de préférence, son style de toast et sa destination.
Ajouter un type = ajouter une ligne ici (+ son texte dans `partials/notification_text.html`).
Aucun import de modèle : ce module est importé par `models.py`.
"""
from dataclasses import dataclass
from typing import Callable, Optional

from django.urls import reverse

# Catégories de préférence = champs booléens de BeerUser. `None` = message système, toujours délivré.
FOLLOW = 'notif_follow'
SOCIAL = 'notif_social'
NETWORK = 'notif_network'
ACHIEVEMENTS = 'notif_achievements'
ESTABLISHMENT = 'notif_establishment'
CATEGORY_FIELDS = (FOLLOW, SOCIAL, NETWORK, ACHIEVEMENTS, ESTABLISHMENT)

Target = Callable[[object], Optional[str]]


def _beer(notif):
    """Fiche de la bière, tant qu'elle est au catalogue."""
    if notif.beer and not notif.beer.is_deleted:
        return reverse('beer_detail', args=[notif.beer.slug])
    return None


def _sender_profile(notif):
    """Profil de l'expéditeur, sauf compte suspendu ou blocage entre les deux membres (page inaccessible)."""
    from ..models import UserBlock

    sender = notif.sender
    if not sender or not sender.is_active:
        return None
    blocked = UserBlock.objects.filter(blocker=notif.recipient_id, blocked=sender.pk).exists() or \
        UserBlock.objects.filter(blocker=sender.pk, blocked=notif.recipient_id).exists()
    return None if blocked else reverse('public_profile', args=[sender.username])


def _place(notif):
    if notif.brewery:
        return reverse('brewery_detail', args=[notif.brewery.slug])
    if notif.bar:
        return reverse('bar_detail', args=[notif.bar.slug])
    return None


def _feedback_thread(notif):
    return reverse('feedback_thread', args=[notif.feedback.slug]) if notif.feedback else None


def _page(url_name):
    return lambda notif: reverse(url_name)


# Ce qui illustre la notification dans la liste
SENDER, SYSTEM, TROPHY = 'sender', 'system', 'trophy'


@dataclass(frozen=True)
class NotificationType:
    key: str
    label: str
    category: Optional[str] = None
    toast: str = 'info'
    target: Optional[Target] = None
    visual: str = SENDER  # SENDER : avatar de l'expéditeur ; SYSTEM : message de l'équipe ; TROPHY : médaille du trophée

    @property
    def is_system(self):
        return self.category is None

    def url_for(self, notif):
        """Page ouverte au clic ; la liste des notifications si la cible n'existe plus ou n'est plus accessible."""
        return (self.target(notif) if self.target else None) or reverse('notifications')

    def image_for(self, notif):
        """URL de l'image à afficher, ou None (la page affiche alors l'icône correspondant au type, jamais une image cassée)."""
        if self.visual != SENDER:
            return None
        if notif.sender:
            return notif.sender.avatar_url
        for related in (notif.beer, notif.brewery, notif.bar):
            if related is not None and getattr(related, 'image', None):
                return related.image.url
        return None


_TYPES = (
    NotificationType('follow', 'Nouvel abonné', FOLLOW, target=_sender_profile),
    NotificationType('beer_shared', 'Bière goûtée en commun', NETWORK, target=_beer),
    NotificationType('beer_added', "Nouvelle bière d'un abonnement", NETWORK, toast='success', target=_beer),
    NotificationType('achievement', 'Nouveau trophée', ACHIEVEMENTS, target=_page('achievements'), visual=TROPHY),
    NotificationType('spot_invite', 'Invitation à un lieu', NETWORK, toast='success', target=_page('map')),
    NotificationType('spot_updated', 'Lieu mis à jour', NETWORK, target=_page('map')),
    NotificationType('beer_updated', 'Bière mise à jour', NETWORK, target=_beer),
    NotificationType('drink_liked', 'Avis aimé', SOCIAL, target=_beer),
    NotificationType('wishlist_added', 'Bière ajoutée à la liste de souhaits', SOCIAL, target=_beer),
    NotificationType('manager_added', "Nommé dans l'équipe d'un établissement", ESTABLISHMENT, target=_place),
    NotificationType('manager_removed', "Retiré de l'équipe d'un établissement", ESTABLISHMENT, toast='error'),
    NotificationType('place_updated', 'Établissement mis à jour', ESTABLISHMENT, target=_place),
    NotificationType('beer_added_to_brewery', 'Bière ajoutée à votre brasserie', ESTABLISHMENT, target=_beer),
    NotificationType('beer_updated_by_manager', 'Bière modifiée par la brasserie', ESTABLISHMENT, target=_beer),
    NotificationType('beer_deleted_by_manager', 'Bière retirée par la brasserie', ESTABLISHMENT),
    # Messages système : ignorent les préférences
    NotificationType('report_updated', 'Signalement mis à jour', toast='warning', target=_page('my_reports'), visual=SYSTEM),
    NotificationType('feedback_replied', 'Réponse à votre feedback', toast='success', target=_feedback_thread, visual=SYSTEM),
    NotificationType('content_removed', 'Contenu retiré par la modération', visual=SYSTEM),
    NotificationType('inactivity_warning', 'Compte bientôt supprimé pour inactivité', toast='warning', target=_page('account'), visual=SYSTEM),
    NotificationType('block_follow_up', 'Un problème avec un membre bloqué ?', target=_page('blocked_users'), visual=SYSTEM),
)

REGISTRY = {t.key: t for t in _TYPES}
CHOICES = [(t.key, t.label) for t in _TYPES]


def get(key):
    """Type déclaré, ou KeyError : un type inconnu est une erreur de programmation, jamais ignorée."""
    try:
        return REGISTRY[key]
    except KeyError:
        raise KeyError(f"Type de notification inconnu : {key!r}") from None
