from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.db.models import Count, Avg, Q, Max
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from ..forms import DrinkForm
from ..models import Beer, Drinks, BeerUser, UserBlock
from .services.recommendations import get_recommended_beers
from .services.selectors import get_filtered_beers, get_filtered_users, get_filtered_notebook_drinks

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
        
        # ALGORITHME DE RECOMMANDATION
        user_drinks = Drinks.objects.filter(drinker_id=request.user)
        recommended_beers = get_recommended_beers(user_drinks, unrated_beers)
            
    # ALGORITHME DE CLASSEMENT
    month = timezone.now().month
    year = timezone.now().year
    
    top = Beer.objects.filter(is_deleted=False).annotate(
        avg_rating=Avg('drinks__note'),
        count_rating=Count('drinks')
    ).filter(avg_rating__isnull=False).order_by('-avg_rating')[:10]
    
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
def load_more_generic(request, item_type):
    """API générique unique (Gateway) pour gérer tous les chargements dynamiques (Load More)."""
    offset = int(request.GET.get('offset', 0))
    limit = 10
    user = request.user
    
    context = {}
    template_name = ""
    items = []
    
    # Aiguillage selon le type demandé
    if item_type == "unrated_beers":
        drunk_beer_ids = Drinks.objects.filter(drinker_id=user).values_list('beer_id', flat=True)
        items = Beer.objects.filter(is_deleted=False).exclude(id__in=drunk_beer_ids).select_related('brewery_id', 'added_by')[offset:offset+limit]
        if items:
            displayed_ids = [b.id for b in items]
            context['unrated_beers'] = items
            context['rating_form'] = DrinkForm()
            context['wishlist_beer_ids'] = list(user.wishlist_beers.filter(id__in=displayed_ids).values_list('id', flat=True))
        template_name = 'partials/unrated_beers.html'
        
    elif item_type == "search_beers":
        base_qs = get_filtered_beers(request)
        if request.GET.get('source') == 'wishlist':
            base_qs = base_qs.filter(wishlisted_by=user)
        items = base_qs[offset:offset+limit]
        if items:
            displayed_ids = [b.id for b in items]
            context['beers'] = items
            context['rating_form'] = DrinkForm()
            context['rated_beer_ids'] = list(Drinks.objects.filter(drinker_id=user, beer_id__in=displayed_ids).values_list('beer_id', flat=True))
            context['wishlist_beer_ids'] = list(user.wishlist_beers.filter(id__in=displayed_ids).values_list('id', flat=True))
        template_name = 'partials/search_beers.html'
        
    elif item_type == "search_users":
        items = get_filtered_users(request)[offset:offset+limit]
        context['users'] = items
        template_name = 'partials/search_users.html'
        
    elif item_type == "notebook_drinks":
        items = get_filtered_notebook_drinks(request)[offset:offset+limit]
        context['my_drinks'] = items
        template_name = 'partials/notebook_drinks.html'
        
    elif item_type == "added_beers":
        items = Beer.objects.filter(added_by=user, is_deleted=False).annotate(
            user_note=Max('drinks__note', filter=Q(drinks__drinker_id=user))
        ).order_by('-id')[offset:offset+limit]
        context['my_added_beers'] = items
        template_name = 'partials/notebook_added_beers.html'
        
    elif item_type == "notebook_feedback":
        items = Drinks.objects.filter(beer_id__added_by=user).exclude(drinker_id=user).select_related('drinker_id', 'beer_id').order_by('-date')[offset:offset+limit]
        context['feedback_on_my_beers'] = items
        template_name = 'partials/notebook_feedback.html'
        
    elif item_type in ["public_added_beers", "public_drinks"]:
        username = request.GET.get('username')
        if not username: 
            return JsonResponse({'error': 'Nom utilisateur manquant'}, status=400)
            
        profile_user = get_object_or_404(BeerUser, username=username)
        
        if UserBlock.objects.filter(Q(blocker=user, blocked=profile_user) | Q(blocker=profile_user, blocked=user)).exists():
            return JsonResponse({'error': 'Profil inaccessible'}, status=403)
            
        if item_type == "public_added_beers":
            items = Beer.objects.filter(added_by=profile_user, is_deleted=False).annotate(
                user_note=Max('drinks__note', filter=Q(drinks__drinker_id=profile_user)),
                count_rating=Count('drinks')
            ).order_by('-id')[offset:offset+limit]
            context['user_added_beers'] = items
            template_name = 'partials/public_added_beers.html'
        else:
            items = Drinks.objects.filter(drinker_id=profile_user).select_related('beer_id', 'beer_id__brewery_id').order_by('-date')[offset:offset+limit]
            context['user_drinks'] = items
            template_name = 'partials/public_drinks.html'
    else:
        return JsonResponse({'error': 'Type de liste invalide'}, status=400)

    # Rendu générique
    if not items:
        return JsonResponse({'html': '', 'has_more': False})
        
    html = render_to_string(template_name, context, request=request)
    return JsonResponse({'html': html, 'has_more': len(items) == limit})