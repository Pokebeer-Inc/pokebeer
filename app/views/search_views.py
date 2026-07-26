from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string
from django.http import JsonResponse

from ..forms import DrinkForm
from ..models import Beer, Drinks
from .services.selectors import get_filtered_beers, get_filtered_users

@login_required(login_url='login')
def load_more_search_users(request):
    """API pour charger les 10 membres suivants dans la recherche."""
    offset = int(request.GET.get('offset', 0))
    limit = 10
    users = get_filtered_users(request)[offset:offset+limit]
    
    if not users:
        return JsonResponse({'html': '', 'has_more': False})
        
    html = render_to_string('partials/search_users.html', {'users': users}, request=request)
    return JsonResponse({'html': html, 'has_more': len(users) == limit})

@login_required(login_url='login')
def all_beers_view(request):
    """Affiche toutes les bières et tous les membres avec système d'onglets."""
    # On utilise nos helpers et on limite le chargement initial à 10 éléments
    beers = get_filtered_beers(request)[:10]
    users = get_filtered_users(request)[:10]

    # Données pour les filtres et les formulaires
    raw_styles = Beer.objects.filter(is_deleted=False).exclude(style__isnull=True).exclude(style='').values_list('style', flat=True)
    unique_styles = set()
    for rs in raw_styles:
        # On découpe chaque chaîne et on ajoute les styles uniques au set
        unique_styles.update([s.strip() for s in rs.split(',') if s.strip()])
    
    # On trie la liste alphabétiquement pour le menu déroulant
    styles = sorted(list(unique_styles))
    
    rating_form = DrinkForm()
    rated_beer_ids = []
    wishlist_beer_ids = []
    if request.user.is_authenticated:
        displayed_ids = [b.id for b in beers]
        rated_beer_ids = list(Drinks.objects.filter(drinker_id=request.user, beer_id__in=displayed_ids).values_list('beer_id', flat=True))
        wishlist_beer_ids = list(request.user.wishlist_beers.filter(id__in=displayed_ids).values_list('id', flat=True))

    user_query = request.GET.get('uq')
    active_tab = 'membres' if (user_query or request.GET.get('tab') == 'membres') else 'bieres'

    context = {
        'beers': beers,
        'rating_form': rating_form,
        'rated_beer_ids': rated_beer_ids,
        'wishlist_beer_ids': wishlist_beer_ids,
        'users': users,
        'active_tab': active_tab,
        'styles': styles,
    }
    return render(request, 'all_beers.html', context)