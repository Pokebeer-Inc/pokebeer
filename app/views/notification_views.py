import json
import re
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import BeerUser, Notification
from ..services import notification_presenter as presenter, notification_types, realtime_service

FCM_TOKEN_MAX_LENGTH = 4096

PAGE_SIZE = 30
TOAST_MAX_AGE = timedelta(days=1)  # au-delà, une alerte non montrée n'a plus d'intérêt en pop-up (elle reste dans la liste)
TOAST_BATCH = 5
SEEN_BATCH = 20
SLUG_PATTERN = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')

LIST_RELATIONS = ('sender', 'beer', 'brewery', 'bar', 'spot', 'report', 'feedback')
LIST_PREFETCH = ('feedback__messages', 'sender__socialaccount_set')  # évite une requête par notification affichée


def _with_achievements(notifications, user):
    """Associe à chaque notification de trophée ses données (calculées une seule fois, et seulement si nécessaire)."""
    trophies = [notif for notif in notifications if notif.notif_type == presenter.ACHIEVEMENT]
    if trophies:
        by_name = presenter.achievements_by_name(user)
        for notif in trophies:
            notif.ach_data = by_name.get(notif.achievement_name)
    return notifications


@login_required(login_url='login')
def notifications_view(request):
    queryset = (Notification.objects.filter(recipient=request.user)
                .select_related(*LIST_RELATIONS).prefetch_related(*LIST_PREFETCH))
    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get('page'))
    _with_achievements(list(page.object_list), request.user)
    return render(request, 'notifications.html', {'page': page, 'notifications': page.object_list})


@login_required(login_url='login')
def api_unread_notifications(request):
    """Alertes à montrer en pop-up : non lues, jamais montrées, récentes. Chacune n'est renvoyée qu'une seule fois.

    Le serveur est la source de vérité (et non le navigateur) : changer d'onglet, relancer l'application Android ou
    recharger la page ne fait plus réapparaître une alerte. `unread_count` est le nombre réel de notifications non lues.
    """
    with transaction.atomic():
        fresh = list(
            Notification.objects.filter(recipient=request.user, is_read=False, toasted_at__isnull=True,
                                        created_at__gte=timezone.now() - TOAST_MAX_AGE)
            .select_related(*LIST_RELATIONS).prefetch_related(*LIST_PREFETCH)
            .select_for_update(of=('self',), skip_locked=True).order_by('-created_at')[:TOAST_BATCH]
        )
        realtime_service.mark_toasted(fresh)

    trophies = presenter.achievements_by_name(request.user) if any(n.notif_type == presenter.ACHIEVEMENT for n in fresh) else {}
    data = [presenter.payload(n, trophies.get(n.achievement_name), request) for n in fresh]
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({'unread_count': unread_count, 'notifications': data})


@require_POST
@login_required(login_url='login')
def api_seen_notifications(request):
    """Le navigateur accuse réception d'un pop-up reçu en temps réel : il ne sera pas remontré au prochain chargement."""
    try:
        slugs = json.loads(request.body).get('slugs')
    except (ValueError, AttributeError):
        slugs = None
    valid = isinstance(slugs, list) and len(slugs) <= SEEN_BATCH and all(isinstance(s, str) and len(s) <= 150 and SLUG_PATTERN.match(s) for s in slugs)
    if not valid:
        return JsonResponse({'ok': False}, status=400)
    # Uniquement les notifications du membre connecté : un slug d'un autre membre est ignoré
    Notification.objects.filter(recipient=request.user, slug__in=slugs, toasted_at__isnull=True).update(toasted_at=timezone.now())
    return JsonResponse({'ok': True})


@login_required(login_url='login')
def read_notification(request, notif_slug):
    """Marque la notification comme lue (et comme montrée) puis ouvre sa page, ou la liste si la cible n'est plus accessible."""
    notif = get_object_or_404(Notification.objects.select_related(*LIST_RELATIONS), slug=notif_slug, recipient=request.user)
    if not notif.is_read or notif.toasted_at is None:
        Notification.objects.filter(pk=notif.pk).update(is_read=True, toasted_at=notif.toasted_at or timezone.now())
    return redirect(notification_types.get(notif.notif_type).url_for(notif))


@require_POST
@login_required(login_url='login')
def mark_all_notifications_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect('notifications')

@require_POST
@login_required(login_url='login')
def delete_notification(request, notif_slug):
    """Supprime la notification définitivement."""
    notif = get_object_or_404(Notification, slug=notif_slug, recipient=request.user)
    notif.delete()
    return redirect('notifications')

@login_required
@require_POST
def update_fcm_token(request):
    """Met à jour le token Firebase (FCM) de l'utilisateur pour les notifications Push."""
    try:
        data = json.loads(request.body)
        token = data.get('token')
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'status': 'error', 'message': 'Données invalides'}, status=400)

    if not isinstance(token, str) or not token.strip():
        return JsonResponse({'status': 'error', 'message': 'Token manquant'}, status=400)

    # Firebase ne garantit pas de longueur maximale (~160 caractères aujourd'hui) : on ne refuse que l'absurde
    if len(token) > FCM_TOKEN_MAX_LENGTH:
        return JsonResponse({'status': 'error', 'message': 'Token trop long'}, status=400)

    # Un appareil n'appartient qu'à un compte : sans cela, après un changement de compte sur le même téléphone,
    # les notifications privées de l'ancien compte seraient encore poussées vers cet appareil
    BeerUser.objects.filter(fcm_token=token).exclude(pk=request.user.pk).update(fcm_token=None)

    # On assigne le nouveau token
    request.user.fcm_token = token
    # On ne sauvegarde QUE la colonne fcm_token en base de données
    request.user.save(update_fields=['fcm_token'])

    return JsonResponse({'status': 'success', 'message': 'Token mis à jour'})