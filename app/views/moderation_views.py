from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from ..models import BeerUser, UserFollow, Report, UserBlock

@login_required(login_url='login')
def my_reports_view(request):
    """Affiche la liste des signalements faits par l'utilisateur."""
    reports = Report.objects.filter(reporter=request.user)
    return render(request, 'my_reports.html', {'reports': reports})

@require_POST
@login_required(login_url='login')
def submit_report(request):
    """Reçoit et enregistre un signalement depuis n'importe quelle modale."""
    item_type = request.POST.get('item_type')
    item_id = request.POST.get('item_id')
    reason = request.POST.get('reason')
    description = request.POST.get('description')
    
    report = Report(reporter=request.user, reason=reason, description=description)
    
    if item_type == 'beer':
        report.reported_beer_id = item_id
    elif item_type == 'drink':
        report.reported_drink_id = item_id
    elif item_type == 'user':
        report.reported_user_id = item_id
        
    report.save()
    messages.success(request, "Votre signalement a été envoyé. Notre équipe va l'examiner.")
    
    referer = request.META.get('HTTP_REFERER', 'index')
    
    # Si l'élément signalé est un utilisateur, on ajoute "?reported=1" à l'URL de retour
    if item_type == 'user' and referer != 'index':
        # On vérifie s'il y a déjà des paramètres dans l'URL pour ne pas casser le lien
        if '?' in referer:
            return redirect(f"{referer}&reported=1")
        else:
            return redirect(f"{referer}?reported=1")
            
    # Redirection classique pour les bières et les notes
    return redirect(referer)

@login_required
@require_POST
def block_user(request, username):
    user_to_block = get_object_or_404(BeerUser, username=username)
    if request.user != user_to_block:
        UserBlock.objects.get_or_create(blocker=request.user, blocked=user_to_block)
        # On supprime les abonnements mutuels s'ils existent
        UserFollow.objects.filter(follower=request.user, followed=user_to_block).delete()
        UserFollow.objects.filter(follower=user_to_block, followed=request.user).delete()
        messages.success(request, f"L'utilisateur {username} a été bloqué.")
    return redirect('index')

@login_required
@require_POST
def unblock_user(request, username):
    user_to_unblock = get_object_or_404(BeerUser, username=username)
    UserBlock.objects.filter(blocker=request.user, blocked=user_to_unblock).delete()
    messages.success(request, f"L'utilisateur {username} a été débloqué.")
    return redirect('blocked_users')

@login_required
def blocked_users_list(request):
    blocked_list = UserBlock.objects.filter(blocker=request.user).select_related('blocked')
    return render(request, 'blocked_users.html', {'blocked_list': blocked_list})