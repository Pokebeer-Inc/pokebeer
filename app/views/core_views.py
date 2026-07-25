from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.db.models import Count, Avg, Q
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from ..forms import DrinkForm
from ..models import Beer, Drinks
from .services.recommendations import get_recommended_beers
from .services.selectors import get_filtered_beers

@ensure_csrf_cookie
@login_required(login_url='login')
def index(request):
    # Bières non notées
    unrated_beers = []
    recommended_beers = []
    rating_form = None

    if request.user.is_authenticated:
        drunk_beer_ids = Drinks.objects.filter(drinker_id=request.user).values_list('beer_id', flat=True)
        unrated_beers = Beer.objects.filter(is_deleted=False).exclude(id__in=drunk_beer_ids).select_related('brewery_id', 'added_by')
        rating_form = DrinkForm()
        
        # --- ALGORITHME DE RECOMMANDATION ---
        user_drinks = Drinks.objects.filter(drinker_id=request.user)
        recommended_beers = get_recommended_beers(user_drinks, unrated_beers)
            
    # --- ALGORITHME DE CLASSEMENT ---
    month = timezone.now().month
    year = timezone.now().year
    
    top = Beer.objects.filter(is_deleted=False).annotate(
        avg_rating=Avg('drinks__note'),
        count_rating=Count('drinks')
    ).order_by('-avg_rating')[:10]
    
    topMonth = Beer.objects.filter(is_deleted=False).annotate(
        avg_rating=Avg('drinks__note', filter=Q(drinks__date__year=year, drinks__date__month=month)),
        count_rating=Count('drinks', filter=Q(drinks__date__year=year, drinks__date__month=month))
    ).filter(avg_rating__isnull=False).order_by('-avg_rating')[:10]

    unrated_beers_display = unrated_beers[:10] if unrated_beers else []
    
    # Wishlist limitée aux bières affichées sur la page d'accueil
    wishlist_beer_ids = []
    if request.user.is_authenticated:
        displayed_ids = set()
        displayed_ids.update([b.id for b in unrated_beers_display])
        displayed_ids.update([b.id for b in recommended_beers])
        displayed_ids.update([b.id for b in top])
        displayed_ids.update([b.id for b in topMonth])
        
        wishlist_beer_ids = list(request.user.wishlist_beers.filter(id__in=displayed_ids).values_list('id', flat=True))

    context = {
        "unrated_beers": unrated_beers_display,
        "recommended_beers": recommended_beers,
        "rating_form": rating_form,
        "top": top,
        "topMonth": topMonth,
        "wishlist_beer_ids": wishlist_beer_ids,
    }
    return render(request, "home.html", context)

@login_required(login_url='login')
def load_more_beers(request):
    """API pour charger les 10 bières suivantes."""
    offset = int(request.GET.get('offset', 0))
    limit = 10
    
    drunk_beer_ids = Drinks.objects.filter(drinker_id=request.user).values_list('beer_id', flat=True)
    unrated_beers = Beer.objects.filter(is_deleted=False).exclude(id__in=drunk_beer_ids).select_related('brewery_id', 'added_by')[offset:offset+limit]
    
    if not unrated_beers:
        return JsonResponse({'html': '', 'has_more': False})
    
    rating_form = DrinkForm()
    
    displayed_ids = [b.id for b in unrated_beers]
    wishlist_beer_ids = list(request.user.wishlist_beers.filter(id__in=displayed_ids).values_list('id', flat=True))
    
    html = render_to_string(
        'partials/unrated_beers.html', 
        {
            'unrated_beers': unrated_beers, 
            'rating_form': rating_form,
            'wishlist_beer_ids': wishlist_beer_ids
        }, 
        request=request
    )
    
    return JsonResponse({'html': html, 'has_more': len(unrated_beers) == limit})

@login_required(login_url='login')
def load_more_search_beers(request):
    """API pour charger les 10 bières suivantes dans la recherche."""
    offset = int(request.GET.get('offset', 0))
    limit = 10
    base_qs = get_filtered_beers(request)
    
    # On filtre uniquement les bières de la wishlist si la requête vient de cette page
    if request.GET.get('source') == 'wishlist':
        base_qs = base_qs.filter(wishlisted_by=request.user)
        
    beers = base_qs[offset:offset+limit]
    
    if not beers:
        return JsonResponse({'html': '', 'has_more': False})
        
    rating_form = DrinkForm()
    
    displayed_ids = [b.id for b in beers]
    rated_beer_ids = list(Drinks.objects.filter(drinker_id=request.user, beer_id__in=displayed_ids).values_list('beer_id', flat=True))
    wishlist_beer_ids = list(request.user.wishlist_beers.filter(id__in=displayed_ids).values_list('id', flat=True))
    
    html = render_to_string(
        'partials/search_beers.html', 
        {
            'beers': beers, 
            'rating_form': rating_form, 
            'rated_beer_ids': rated_beer_ids,
            'wishlist_beer_ids': wishlist_beer_ids
        }, 
        request=request
    )
    
    return JsonResponse({'html': html, 'has_more': len(beers) == limit})
