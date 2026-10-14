"""Suggestion de modification d'une fiche (bière, brasserie, bar) par un membre qui ne peut pas la modifier directement."""
from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from ..services.moderation.content import CONTENT_TYPES
from ..services.moderation.suggestions import SuggestionError, propose
from .utils import previous_page


@require_POST
def suggest_edit_view(request, kind, slug):
    """Enregistre la suggestion (relue par l'équipe) puis renvoie sur la fiche."""
    content = CONTENT_TYPES.get(kind)
    target = content.find(slug) if content and content.suggest_fields else None
    back = content.url(target) if target else previous_page(request)
    try:
        propose(kind, slug, request.user, request.POST)
    except SuggestionError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Merci ! Votre suggestion a été transmise à l'équipe, qui la relira.")
    return redirect(back)
