"""Échanges du membre avec l'équipe : liste de ses fils et conversation. Un membre ne voit jamais le fil d'un autre (404)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from ..forms import FeedbackReplyForm
from ..models import Feedback, Notification
from ..services import feedback as conversations


def _own_threads(user):
    return Feedback.objects.filter(user=user).prefetch_related('messages')


@login_required(login_url='login')
def team_messages_view(request):
    """Tous les échanges du membre, le plus récemment actif en premier, avec le dernier message de chacun."""
    rows = []
    for feedback in _own_threads(request.user):
        entries = conversations.timeline(feedback)
        rows.append({'feedback': feedback, 'last': entries[-1], 'count': len(entries)})
    rows.sort(key=lambda row: row['last'].created_at, reverse=True)
    return render(request, 'team_messages.html', {'threads': rows})


@login_required(login_url='login')
def feedback_thread_view(request, feedback_slug):
    """Conversation complète (premier message compris) et réponse du membre."""
    feedback = get_object_or_404(_own_threads(request.user), slug=feedback_slug)

    if request.method == 'POST':
        form = FeedbackReplyForm(request.POST)
        if form.is_valid():
            try:
                conversations.member_reply(feedback, request.user, form.cleaned_data['body'])
                messages.success(request, "Message envoyé à l'équipe.")
                return redirect('feedback_thread', feedback_slug=feedback.slug)
            except conversations.FeedbackError as error:
                messages.error(request, str(error))
        else:
            messages.error(request, "Votre message n'a pas pu être envoyé : vérifiez sa longueur.")
    else:
        form = FeedbackReplyForm()
        # Lire l'échange vaut lecture des notifications de réponse qui s'y rapportent
        Notification.objects.filter(recipient=request.user, feedback=feedback, is_read=False).update(is_read=True, toasted_at=timezone.now())

    return render(request, 'feedback_thread.html', {
        'feedback': feedback,
        'entries': conversations.timeline(feedback),
        'form': form,
        'max_length': conversations.MAX_BODY_LENGTH,
    })
