from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from ..models import Notification
from .utils import get_user_achievements

@login_required(login_url='login')
def notifications_view(request):
    notifications = Notification.objects.filter(recipient=request.user)
    
    # On récupère toutes les données des trophées (incluant les styles/couleurs)
    achievements_data = get_user_achievements(request.user)
    achievements_dict = {ach['name']: ach for ach in achievements_data}
    
    for notif in notifications:
        if notif.notif_type == 'achievement' and notif.achievement_name in achievements_dict:
            ach_data = achievements_dict[notif.achievement_name]
            notif.svg_icon = ach_data['icon']
            notif.ach_style = ach_data['style']  # On associe les couleurs au niveau
            
    return render(request, 'notifications.html', {'notifications': notifications})

@login_required(login_url='login')
def read_notification(request, notif_id):
    """Marque la notification comme lue et redirige au bon endroit."""
    notif = get_object_or_404(Notification, id=notif_id, recipient=request.user)
    notif.is_read = True
    notif.save()
    
    if notif.notif_type == 'follow' and notif.sender:
        return redirect('public_profile', username=notif.sender.username)
    elif notif.notif_type in ['beer_shared', 'beer_added', 'beer_updated', 'drink_liked'] and notif.beer:
        return redirect('beer_detail', beer_slug=notif.beer.slug)
    elif notif.notif_type == 'achievement':
        return redirect('achievements')
    elif notif.notif_type in ['spot_invite', 'spot_updated']:
        return redirect('map')
        
    return redirect('notifications')

@login_required(login_url='login')
def delete_notification(request, notif_id):
    """Supprime la notification définitivement."""
    notif = get_object_or_404(Notification, id=notif_id, recipient=request.user)
    notif.delete()
    return redirect('notifications')