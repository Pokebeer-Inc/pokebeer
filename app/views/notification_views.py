from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.urls import reverse
import json

from ..models import BeerUser, Notification
from ..services import notification_types
from .utils import get_user_achievements

FCM_TOKEN_MAX_LENGTH = 4096

@login_required(login_url='login')
def notifications_view(request):
    notifications = Notification.objects.filter(recipient=request.user).select_related('sender', 'beer', 'brewery', 'bar', 'spot', 'report', 'feedback')
    
    achievements_data, _ = get_user_achievements(request.user)
    achievements_dict = {ach['name']: ach for ach in achievements_data}
    
    for notif in notifications:
        if notif.notif_type == 'achievement' and notif.achievement_name in achievements_dict:
            notif.ach_data = achievements_dict[notif.achievement_name]
            
    return render(request, 'notifications.html', {'notifications': notifications})

@login_required(login_url='login')
def api_unread_notifications(request):
    notifications = Notification.objects.filter(
        recipient=request.user, 
        is_read=False
    ).select_related('sender', 'beer', 'brewery', 'bar', 'spot', 'report', 'feedback').order_by('-created_at')[:5]
    
    achievements_data, _ = get_user_achievements(request.user)
    achievements_dict = {ach['name']: ach for ach in achievements_data}
    
    data = []
    for notif in notifications:
        icon_html = None
        tier_slug = None
        toast_type = notification_types.get(notif.notif_type).toast
        
        if notif.notif_type == 'achievement' and notif.achievement_name in achievements_dict:
            ach_data = achievements_dict[notif.achievement_name]
            tier_slug = ach_data['tier_slug']
            icon_html = render_to_string('partials/achievement_icon.html', {'slug': ach_data['slug']}, request=request).strip()

        data.append({
            'slug': notif.slug,
            'notif_type': notif.notif_type,
            'message': render_to_string('partials/notification_text.html', {'notif': notif}, request=request).strip(),
            'read_url': reverse('read_notification', args=[notif.slug]),
            'time_ago': notif.time_ago,
            'icon': icon_html,
            'tier_slug': tier_slug,
            'toastType': toast_type
        })
        
    return JsonResponse({'unread_count': len(data), 'notifications': data})

@login_required(login_url='login')
def read_notification(request, notif_slug):
    """Marque la notification comme lue et redirige au bon endroit."""
    notif = get_object_or_404(Notification, slug=notif_slug, recipient=request.user)
    notif.is_read = True
    notif.save()
    
    return redirect(notification_types.get(notif.notif_type).url_for(notif))

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