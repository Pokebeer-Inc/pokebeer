from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.urls import reverse
import json

from ..models import Notification
from .utils import get_user_achievements

@login_required(login_url='login')
def notifications_view(request):
    notifications = Notification.objects.filter(recipient=request.user).select_related('sender', 'beer', 'spot')
    
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
    ).select_related('sender', 'beer', 'spot', 'report').order_by('-created_at')[:5]
    
    achievements_data, _ = get_user_achievements(request.user)
    achievements_dict = {ach['name']: ach for ach in achievements_data}
    
    data = []
    for notif in notifications:
        icon_html = None
        tier_slug = None
        toast_type = 'info'
        
        if notif.notif_type == 'achievement' and notif.achievement_name in achievements_dict:
            ach_data = achievements_dict[notif.achievement_name]
            tier_slug = ach_data['tier_slug']
            icon_html = render_to_string('partials/achievement_icon.html', {'slug': ach_data['slug']}, request=request).strip()
        elif notif.notif_type == 'report_updated':
            toast_type = 'warning'
        elif notif.notif_type in ['beer_added', 'spot_invite', 'feedback_replied']:
            toast_type = 'success'
        elif notif.notif_type in ['manager_added', 'place_updated', 'beer_added_to_brewery', 'beer_updated_by_manager', 'beer_deleted_by_manager']:
            toast_type = 'info'
        elif notif.notif_type == 'manager_removed':
            toast_type = 'error'
            
        data.append({
            'id': notif.id,
            'notif_type': notif.notif_type,
            'message': render_to_string('partials/notification_text.html', {'notif': notif}, request=request).strip(),
            'read_url': reverse('read_notification', args=[notif.id]),
            'time_ago': notif.time_ago,
            'icon': icon_html,
            'tier_slug': tier_slug,
            'toastType': toast_type
        })
        
    return JsonResponse({'unread_count': len(data), 'notifications': data})

@login_required(login_url='login')
def read_notification(request, notif_id):
    """Marque la notification comme lue et redirige au bon endroit."""
    notif = get_object_or_404(Notification, id=notif_id, recipient=request.user)
    notif.is_read = True
    notif.save()
    
    if notif.notif_type == 'follow' and notif.sender:
        return redirect('public_profile', username=notif.sender.username)
    elif notif.notif_type in ['beer_shared', 'beer_added', 'beer_updated', 'drink_liked', 'wishlist_added', 'beer_added_to_brewery', 'beer_updated_by_manager'] and notif.beer:
        return redirect('beer_detail', beer_slug=notif.beer.slug)
    elif notif.notif_type == 'achievement':
        return redirect('achievements')
    elif notif.notif_type in ['spot_invite', 'spot_updated']:
        return redirect('map')
    elif notif.notif_type == 'report_updated':
        return redirect('my_reports')
    elif notif.notif_type == 'feedback_replied':
        return redirect('account')
    elif notif.notif_type in ['manager_added', 'place_updated'] and notif.brewery:
        return redirect('brewery_detail', brewery_id=notif.brewery.id)
    return redirect('notifications')

@login_required(login_url='login')
def delete_notification(request, notif_id):
    """Supprime la notification définitivement."""
    notif = get_object_or_404(Notification, id=notif_id, recipient=request.user)
    notif.delete()
    return redirect('notifications')

@login_required
@require_POST
def update_fcm_token(request):
    """Met à jour le token Firebase (FCM) de l'utilisateur pour les notifications Push."""
    try:
        data = json.loads(request.body)
        token = data.get('token')
        
        if token:
            # On assigne le nouveau token
            request.user.fcm_token = token
            # On ne sauvegarde QUE la colonne fcm_token en base de données
            request.user.save(update_fields=['fcm_token']) 
            
            return JsonResponse({'status': 'success', 'message': 'Token mis à jour'})
            
        return JsonResponse({'status': 'error', 'message': 'Token manquant'}, status=400)
        
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Données invalides'}, status=400)