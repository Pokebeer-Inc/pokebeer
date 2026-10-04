from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from urllib.parse import quote
from django.views.decorators.http import require_POST

from ..forms import ReportForm, error_summary
from ..models import BeerUser, UserFollow, Report, UserBlock
from ..services.blocks import invite_blockers_to_report
from ..services.threads import report_entries
from .utils import previous_page

@login_required(login_url='login')
def my_reports_view(request):
    """Affiche la liste des signalements faits par l'utilisateur."""
    reports = (Report.objects.filter(reporter=request.user)
               .select_related('reported_beer', 'reported_user', 'reported_drink__beer_id', 'reported_brewery'))
    return render(request, 'my_reports.html', {'reports': [{'report': r, 'entries': report_entries(r)} for r in reports]})

@require_POST
@login_required(login_url='login')
def submit_report(request):
    """Reçoit et enregistre un signalement depuis n'importe quelle modale."""
    form = ReportForm(request.POST, reporter=request.user)

    referer = previous_page(request)

    if not form.is_valid():
        messages.error(request, "Votre signalement n'a pas pu être envoyé : " + " ; ".join(error_summary(form)))
        return redirect(referer)

    form.save()
    messages.success(request, "Votre signalement a été envoyé. Notre équipe va l'examiner.")

    # Si l'élément signalé est un utilisateur, on ajoute "?reported=1" à l'URL de retour
    if form.cleaned_data['item_type'] == 'user':
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
        invite_blockers_to_report(user_to_block)
        messages.success(request, f"L'utilisateur {username} a été bloqué.")
        # On l'emmène là où il peut signaler le membre tout de suite s'il y a un problème
        return redirect(f"{reverse('blocked_users')}?just_blocked={quote(user_to_block.username)}")
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
    blocked_list = UserBlock.objects.filter(blocker=request.user).select_related('blocked').prefetch_related('blocked__socialaccount_set')
    # Le paramètre n'est qu'un indice d'affichage : il n'est pris en compte que pour un membre réellement bloqué par l'utilisateur
    just_blocked = request.GET.get('just_blocked')
    just_blocked = next((b.blocked.username for b in blocked_list if b.blocked.username == just_blocked), None)
    return render(request, 'blocked_users.html', {'blocked_list': blocked_list, 'just_blocked': just_blocked})