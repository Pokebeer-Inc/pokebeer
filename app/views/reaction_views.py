"""Réactions aux avis (pouces) et liste de souhaits."""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
import json

from ..models import Beer, Drinks, DrinkReaction
from ..services.members.achievements import check_and_notify_achievements
from ..services.messaging.notifications import notify
from ..services.members.visibility import exclude_blocked

def _reaction_choice(request):
    """`is_like` du corps JSON (True = pouce en l'air, False = pouce en bas), ou None si la requête est invalide."""
    try:
        is_like = json.loads(request.body).get('is_like')
    except (ValueError, AttributeError):
        return None
    return is_like if isinstance(is_like, bool) else None

@require_POST
@login_required(login_url='login')
def toggle_reaction_view(request, drink_slug):
    """API pour liker/disliker un avis."""
    is_like = _reaction_choice(request)
    if is_like is None:
        return JsonResponse({'success': False, 'error': "Requête invalide."}, status=400)

    # Un avis d'un membre bloqué ou suspendu n'est pas visible : il n'est pas réactionnable
    visible = exclude_blocked(Drinks.objects.filter(drinker__is_active=True), request.user, 'drinker')
    drink = get_object_or_404(visible.select_related('beer', 'drinker'), slug=drink_slug)
    if drink.drinker == request.user:
        return JsonResponse({'success': False, 'error': "Vous ne pouvez pas réagir à votre propre avis."}, status=400)

    with transaction.atomic():
        reaction, created = DrinkReaction.objects.select_for_update().get_or_create(
            user=request.user, drink=drink, defaults={'is_like': is_like},
        )
        current_reaction = is_like
        if created:
            notifies = is_like
        elif reaction.is_like == is_like:
            reaction.delete()  # Clic sur le même bouton = annulation
            current_reaction, notifies = None, False
        else:
            reaction.is_like = is_like  # Changement d'avis (ex : passe de Like à Dislike)
            reaction.save(update_fields=['is_like'])
            notifies = is_like

    if notifies:
        notify('drink_liked', [drink.drinker], sender=request.user, beer=drink.beer)
    check_and_notify_achievements(request.user)

    counts = drink.reactions.aggregate(
        likes=Count('id', filter=Q(is_like=True)), dislikes=Count('id', filter=Q(is_like=False)),
    )
    return JsonResponse({
        'success': True,
        'score': counts['likes'] - counts['dislikes'],
        'likes': counts['likes'],
        'dislikes': counts['dislikes'],
        'current_reaction': current_reaction,
    })

@require_POST
@login_required(login_url='login')
def toggle_wishlist(request, beer_slug):
    """API pour ajouter/retirer une bière de la wishlist."""
    user = request.user
    beer = get_object_or_404(Beer, slug=beer_slug)

    if user.wishlist_beers.filter(pk=beer.pk).exists():
        user.wishlist_beers.remove(beer)  # retirer reste toujours possible
        is_in_wishlist = False
    else:
        # On n'ajoute que ce qui est visible : bière du catalogue, d'un membre non bloqué
        get_object_or_404(exclude_blocked(Beer.objects.filter(is_deleted=False), user, 'added_by'), pk=beer.pk)
        user.wishlist_beers.add(beer)
        is_in_wishlist = True

        # Notification au créateur de la bière
        if beer.added_by and beer.added_by != user:
            notify('wishlist_added', [beer.added_by], sender=user, beer=beer)

    return JsonResponse({'success': True, 'is_in_wishlist': is_in_wishlist})
