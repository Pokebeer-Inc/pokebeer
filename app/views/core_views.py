from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.db.models import Count, Q, Max
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from ..forms import DrinkForm
from ..models import Beer, Drinks, BeerUser, UserBlock
from .services.recommendations import get_recommended_beers
from .services.selectors import get_activity, activity_kind, ACTIVITY_TITLES, get_filtered_bars, get_filtered_beers, get_filtered_breweries, get_filtered_users, get_filtered_notebook_drinks, get_wishlist_beers
from ..services.places import BAR, BREWERY, with_targets
from .utils import parse_offset
from .search_views import build_results, normalize_tab

HOME_RECOMMENDATIONS = 10
HOME_ACTIVITY = 10


def unrated_beers_for(user):
    """Bières du catalogue que le membre n'a pas encore notées (sous-requête : rien n'est chargé en mémoire)."""
    return (Beer.objects.filter(is_deleted=False)
            .exclude(id__in=Drinks.objects.filter(drinker_id=user).values('beer_id'))
            .select_related('brewery_id', 'added_by'))


@ensure_csrf_cookie
@login_required(login_url='login')
def index(request):
    """Recherche = accueil : sans saisie, recommandations et fil d'activité ; avec `q` ou un onglet, les résultats."""
    user = request.user
    # Sans paramètre (ou avec l'onglet « Tout » seul) on affiche l'accueil, sinon les résultats de recherche
    searching = bool(request.GET.get('q') or request.GET.get('uq') or normalize_tab(request.GET.get('tab')) not in (None, '', 'all'))

    recommended = get_recommended_beers(Drinks.objects.filter(drinker_id=user), unrated_beers_for(user), HOME_RECOMMENDATIONS)
    activity = get_activity(user, HOME_ACTIVITY)
    kind = activity_kind(activity)
    context = {
        'greeting': 'Bonjour' if timezone.localtime().hour < 18 else 'Bonsoir',  # le navigateur l'ajuste à l'heure de l'appareil
        'searching': searching,
        'recommended_beers': list(recommended),
        'activity': activity,
        'activity_kind': kind,
        'activity_title': ACTIVITY_TITLES[kind],
    }
    context.update(build_results(request, default_tab='all'))
    return render(request, 'home.html', context)


@login_required(login_url='login')
def load_more_generic(request, item_type):
    """API générique unique (Gateway) pour gérer tous les chargements dynamiques (Load More)."""
    offset = parse_offset(request)
    if offset is None:
        return JsonResponse({'error': 'Offset invalide'}, status=400)
    limit = 10
    user = request.user
    
    context = {}
    template_name = ""
    items = []
    
    # Aiguillage selon le type demandé
    if item_type == "search_beers":
        items = get_filtered_beers(request)[offset:offset+limit]
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
        
    elif item_type == "search_breweries":
        items = context['places'] = with_targets(get_filtered_breweries(request)[offset:offset+limit], BREWERY)
        context['place_kind'] = 'brewery'
        template_name = 'partials/search_places.html'

    elif item_type == "search_bars":
        items = context['places'] = with_targets(get_filtered_bars(request)[offset:offset+limit], BAR)
        context['place_kind'] = 'bar'
        template_name = 'partials/search_places.html'

    elif item_type == "wishlist_tiles":
        items = context['wishlist_beers'] = list(get_wishlist_beers(request)[offset:offset+limit])
        context['rating_form'] = DrinkForm()
        template_name = 'partials/wishlist_tiles.html'

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
            
        profile_user = get_object_or_404(BeerUser, username=username, is_active=True)
        
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