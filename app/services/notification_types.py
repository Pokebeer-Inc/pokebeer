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
    return reverse('beer_detail', args=[notif.beer.slug]) if notif.beer else None


def _sender_profile(notif):
    return reverse('public_profile', args=[notif.sender.username]) if notif.sender else None


def _place(notif):
    if notif.brewery:
        return reverse('brewery_detail', args=[notif.brewery.slug])
    if notif.bar:
        return reverse('bar_detail', args=[notif.bar.slug])
    return None


def _page(url_name):
    return lambda notif: reverse(url_name)


@dataclass(frozen=True)
class NotificationType:
    key: str
    label: str
    category: Optional[str] = None
    toast: str = 'info'
    target: Optional[Target] = None

    @property
    def is_system(self):
        return self.category is None

    def url_for(self, notif):
        """Page ouverte au clic ; la liste des notifications si la cible n'existe plus."""
        return (self.target(notif) if self.target else None) or reverse('notifications')


_TYPES = (
    NotificationType('follow', 'Nouvel abonné', FOLLOW, target=_sender_profile),
    NotificationType('beer_shared', 'Bière goûtée en commun', NETWORK, target=_beer),
    NotificationType('beer_added', "Nouvelle bière d'un abonnement", NETWORK, toast='success', target=_beer),
    NotificationType('achievement', 'Nouveau trophée', ACHIEVEMENTS, target=_page('achievements')),
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
    NotificationType('report_updated', 'Signalement mis à jour', toast='warning', target=_page('my_reports')),
    NotificationType('feedback_replied', 'Réponse à votre feedback', toast='success', target=_page('account')),
    NotificationType('content_removed', 'Contenu retiré par la modération'),
    NotificationType('block_follow_up', 'Un problème avec un membre bloqué ?', target=_page('blocked_users')),
)

REGISTRY = {t.key: t for t in _TYPES}
CHOICES = [(t.key, t.label) for t in _TYPES]


def get(key):
    """Type déclaré, ou KeyError : un type inconnu est une erreur de programmation, jamais ignorée."""
    try:
        return REGISTRY[key]
    except KeyError:
        raise KeyError(f"Type de notification inconnu : {key!r}") from None
