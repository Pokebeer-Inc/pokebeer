"""Tirage du jour : ouverture et progression (JSON consommé par script/daily_draw.js)."""
import json
from functools import wraps

from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..domain import rarity
from ..services.catalog import daily_draw


def _card(card, wishlisted):
    beer = card.beer
    return {
        'rarity': card.rarity,
        'rarity_label': rarity.get(card.rarity).label,
        'name': beer.name,
        'brewery': beer.brewery_label,
        'style': beer.style or '',
        'degree': f'{beer.degree.normalize():f}',
        'image': beer.image.url if beer.image else '',
        'beer_url': reverse('beer_detail', args=[beer.slug]),
        'rate_url': f"{reverse('beer_detail', args=[beer.slug])}#modalRate-{beer.slug}",  # la fiche, avec la fenêtre de notation ouverte
        'slug': beer.slug,
        'in_wishlist': beer.pk in wishlisted,
    }


def _feature_enabled(view):
    """Refuse (403) un membre qui a désactivé le tirage du jour : l'interrupteur vaut côté serveur, pas seulement dans l'accueil."""
    @wraps(view)
    def guarded(request):
        if not getattr(request.user, daily_draw.FEATURE):
            return JsonResponse({'success': False, 'error': "Le tirage du jour est désactivé dans vos réglages."}, status=403)
        return view(request)
    return guarded


@require_POST
@_feature_enabled
def open_daily_draw(request):
    """Ouvre le tirage du jour (le crée au premier appel, le renvoie tel quel ensuite) : jamais deux tirages pour une même journée."""
    draw = daily_draw.open_today(request.user)
    if draw is None:
        return JsonResponse({'success': False, 'error': "Vous avez déjà goûté toutes les bières du catalogue."}, status=404)
    cards = list(draw.cards.all())
    wishlisted = set(request.user.wishlist_beers.filter(pk__in=[card.beer_id for card in cards]).values_list('pk', flat=True))
    return JsonResponse({'success': True, 'revealed': draw.revealed, 'cards': [_card(card, wishlisted) for card in cards]})


@require_POST
@_feature_enabled
def reveal_daily_draw(request):
    """Nombre de cartes retournées jusqu'ici (JSON `{"count": n}`) : l'accueil propose de reprendre à la suivante, pas au début."""
    try:
        count = json.loads(request.body).get('count')
    except (ValueError, AttributeError):
        count = None
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return JsonResponse({'success': False, 'error': "Requête invalide."}, status=400)
    revealed = daily_draw.reveal(request.user, count)
    if revealed is None:
        return JsonResponse({'success': False, 'error': "Aucun tirage aujourd'hui."}, status=404)
    return JsonResponse({'success': True, 'revealed': revealed})
