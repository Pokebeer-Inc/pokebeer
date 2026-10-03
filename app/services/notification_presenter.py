"""Représentation d'une notification pour le navigateur et les appareils : une seule construction, utilisée par l'API
des notifications non lues, la diffusion temps réel (WebSocket) et le push Android."""
from django.template.loader import render_to_string
from django.urls import reverse

from . import notification_types

ACHIEVEMENT = 'achievement'


def achievements_by_name(recipient, cache=None):
    """Trophées d'un destinataire indexés par nom, calculés une seule fois par destinataire quand un cache est fourni."""
    # Import local pour éviter les imports circulaires
    from .achievements import get_user_achievements

    if cache is not None and recipient.pk in cache:
        return cache[recipient.pk]
    achievements, _level = get_user_achievements(recipient)
    by_name = {achievement['name']: achievement for achievement in achievements}
    if cache is not None:
        cache[recipient.pk] = by_name
    return by_name


def message_html(notif, request=None):
    """Texte de la notification (HTML échappé par le moteur de templates)."""
    return render_to_string('partials/notification_text.html', {'notif': notif}, request=request).strip()


def read_path(notif):
    return reverse('read_notification', args=[notif.slug])


def payload(notif, achievement=None, request=None):
    """Données d'une notification pour l'affichage d'un pop-up ou d'une liste."""
    notif_type = notification_types.get(notif.notif_type)
    icon, tier_slug = None, None
    if achievement:
        tier_slug = achievement['tier_slug']
        icon = render_to_string('partials/achievement_icon.html', {'slug': achievement['slug']}, request=request).strip()
    return {
        'slug': notif.slug,
        'notif_type': notif.notif_type,
        'message': message_html(notif, request),
        'read_url': read_path(notif),
        'time_ago': notif.time_ago,
        'icon': icon,
        'tier_slug': tier_slug,
        'toastType': notif_type.toast,
        'image_url': notif_type.image_for(notif),
    }
