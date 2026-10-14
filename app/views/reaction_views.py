"""Réactions aux avis (pouces) et liste de souhaits."""
import json

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from ..models import Beer, Drinks
from ..services.catalog import reactions
from ..services.members.visibility import exclude_blocked


def _reaction_choice(request):
    """`is_like` du corps JSON (True = pouce en l'air, False = pouce en bas), ou None si la requête est invalide."""
    try:
        is_like = json.loads(request.body).get('is_like')
    except (ValueError, AttributeError):
        return None
    return is_like if isinstance(is_like, bool) else None

@require_POST
def toggle_reaction_view(request, drink_slug):
    """API pour liker/disliker un avis."""
    is_like = _reaction_choice(request)
    if is_like is None:
        return JsonResponse({'success': False, 'error': "Requête invalide."}, status=400)

    # Un avis d'un membre bloqué ou suspendu n'est pas visible : il n'est pas réactionnable
    visible = exclude_blocked(Drinks.objects.filter(drinker__is_active=True), request.user, 'drinker')
    drink = get_object_or_404(visible.select_related('beer', 'drinker'), slug=drink_slug)
    try:
        current_reaction, counts = reactions.toggle_reaction(request.user, drink, is_like)
    except reactions.OwnReview:
        return JsonResponse({'success': False, 'error': "Vous ne pouvez pas réagir à votre propre avis."}, status=400)
    return JsonResponse({
        'success': True,
        'score': counts['likes'] - counts['dislikes'],
        'likes': counts['likes'],
        'dislikes': counts['dislikes'],
        'current_reaction': current_reaction,
    })


@require_POST
def toggle_wishlist(request, beer_slug):
    """API pour ajouter/retirer une bière de la wishlist."""
    beer = get_object_or_404(Beer, slug=beer_slug)
    # On n'ajoute que ce qui est visible : bière du catalogue, d'un membre non bloqué
    visible = exclude_blocked(Beer.objects.filter(pk=beer.pk, is_deleted=False), request.user, 'added_by').exists()
    try:
        is_in_wishlist = reactions.toggle_wishlist(request.user, beer, can_add=visible)
    except PermissionError:
        raise Http404 from None
    return JsonResponse({'success': True, 'is_in_wishlist': is_in_wishlist})
