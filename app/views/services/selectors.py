from django.db.models import Case, When, Value, IntegerField, OuterRef, Q, Max, Prefetch, Count, Subquery

from ...models import Bar, Beer, BeerUser, Brewery, Drinks
from ...services import place_filters, search
from ...services.places import BAR, BREWERY
from ..utils import get_blocked_users, get_excluded_users


def search_query(request):
    """Texte de la barre de recherche unique (`q`) ; `uq` est l'ancien paramètre de la recherche de membres."""
    return (request.GET.get('q') or request.GET.get('uq') or '').strip()

def get_filtered_beers(request):
    """Extrait la logique de filtrage des bières pour la réutiliser."""
    # Bloqués seulement : le catalogue est partagé, les bières d'un compte suspendu restent visibles
    beers = Beer.objects.filter(is_deleted=False).exclude(added_by__in=get_blocked_users(request.user)).select_related('brewery_id')

    query = search_query(request)
    beers = search.beers(beers, query)

    degree_filter = request.GET.get('degree')
    if degree_filter == 'light': beers = beers.filter(degree__lt=5)
    elif degree_filter == 'regular': beers = beers.filter(degree__gte=5, degree__lte=8)
    elif degree_filter == 'strong': beers = beers.filter(degree__gt=8)

    ibu_filter = request.GET.get('ibu')
    if ibu_filter == 'low': beers = beers.filter(bitterness__lt=20)
    elif ibu_filter == 'medium': beers = beers.filter(bitterness__gte=20, bitterness__lte=50)
    elif ibu_filter == 'high': beers = beers.filter(bitterness__gt=50)
        
    style_filter = request.GET.get('style')
    if style_filter: beers = beers.filter(style__icontains=style_filter)

    # Avec une recherche et sans tri choisi, les meilleures correspondances passent d'abord
    order_fields = [search.RANK_FIELD] if query and not request.GET.get('sort') else []
    
    # Logique de Tri
    sort_by = request.GET.get('sort', 'unrated_first')
    
    if sort_by == 'name_asc':
        order_fields.append('name')
    elif sort_by == 'name_desc':
        order_fields.append('-name')
    elif sort_by == 'degree_desc':
        order_fields.extend(['-degree', 'name'])
    elif sort_by == 'degree_asc':
        order_fields.extend(['degree', 'name'])
    elif sort_by == 'ibu_desc':
        order_fields.extend(['-bitterness', 'name'])
    elif sort_by == 'ibu_asc':
        order_fields.extend(['bitterness', 'name'])
    elif sort_by == 'date_asc':
        order_fields.append('id')
    elif sort_by == 'date_desc':
        order_fields.append('-id')
    else: # unrated_first (défaut)
        if request.user.is_authenticated:
            rated_beer_ids = list(Drinks.objects.filter(drinker_id=request.user).values_list('beer_id', flat=True))
            if rated_beer_ids:
                # Annotation dynamique uniquement si nécessaire
                beers = beers.annotate(
                    is_rated=Case(When(id__in=rated_beer_ids, then=Value(1)), default=Value(0), output_field=IntegerField())
                )
                order_fields.append('is_rated')
        
        # En second critère, on trie par les ajouts les plus récents
        order_fields.append('-id')
        
    beers = beers.order_by(*order_fields)
        
    return beers

def get_filtered_users(request):
    """Extrait la logique de filtrage des utilisateurs pour la réutiliser."""
    user_query = search_query(request)
    
    excluded_ids = get_excluded_users(request.user)
    if request.user.is_authenticated:
        excluded_ids.append(request.user.id)
    
    latest_beer_prefetch = Prefetch(
        'added_beers',
        queryset=Beer.objects.filter(is_deleted=False).select_related('brewery_id').order_by('-id'),
        to_attr='latest_beers_list'
    )
    
    users = BeerUser.objects.exclude(id__in=excluded_ids).prefetch_related(latest_beer_prefetch, 'socialaccount_set')
    
    if user_query:
        users = search.members(users, user_query).order_by(search.RANK_FIELD, 'username')
    else:
        users = users.filter(added_beers__is_deleted=False).annotate(latest_beer_id=Max('added_beers__id')).order_by('-latest_beer_id')
        
    return users

def get_filtered_breweries(request):
    """Brasseries correspondant à la recherche et aux filtres (les plus pertinentes, puis les plus fournies en bières)."""
    breweries = Brewery.objects.annotate(beer_count=Count('beer', filter=Q(beer__is_deleted=False), distinct=True))
    breweries = place_filters.apply(search.breweries(breweries, search_query(request)), request.GET, BREWERY)
    return breweries.order_by(*place_filters.ordering(request.GET, (search.RANK_FIELD, '-beer_count', 'name')))

def get_filtered_bars(request):
    """Bars correspondant à la recherche et aux filtres."""
    bars = place_filters.apply(search.bars(Bar.objects.all(), search_query(request)), request.GET, BAR)
    return bars.order_by(*place_filters.ordering(request.GET, (search.RANK_FIELD, 'name')))

def get_filtered_notebook_drinks(request):
    """Extrait la logique de filtrage des dégustations du carnet."""
    drinks = Drinks.objects.filter(drinker_id=request.user).select_related('beer_id', 'beer_id__brewery_id')
    
    # Filtrage par carnet personnalisé
    notebook_slug = request.GET.get('notebook_slug')
    if notebook_slug:
        drinks = drinks.filter(notebooks__slug=notebook_slug)

    query = request.GET.get('q')
    if query:
        drinks = drinks.filter(Q(beer_id__name__icontains=query) | Q(beer_id__brewery_id__name__icontains=query))

    degree_filter = request.GET.get('degree')
    if degree_filter == 'light': drinks = drinks.filter(beer_id__degree__lt=5)
    elif degree_filter == 'regular': drinks = drinks.filter(beer_id__degree__gte=5, beer_id__degree__lte=8)
    elif degree_filter == 'strong': drinks = drinks.filter(beer_id__degree__gt=8)

    ibu_filter = request.GET.get('ibu')
    if ibu_filter == 'low': drinks = drinks.filter(beer_id__bitterness__lt=20)
    elif ibu_filter == 'medium': drinks = drinks.filter(beer_id__bitterness__gte=20, beer_id__bitterness__lte=50)
    elif ibu_filter == 'high': drinks = drinks.filter(beer_id__bitterness__gt=50)

    style_filter = request.GET.get('style')
    if style_filter: 
        drinks = drinks.filter(beer_id__style__icontains=style_filter)

    # Fourchette de notes : appliquée seulement si elle restreint (0-10 laisserait de côté les avis sans note)
    rating_min, rating_max = request.GET.get('rating_min', ''), request.GET.get('rating_max', '')
    if rating_min.isdigit() and int(rating_min) > 0:
        drinks = drinks.filter(note__gte=min(10, int(rating_min)))
    if rating_max.isdigit() and int(rating_max) < 10:
        drinks = drinks.filter(note__lte=int(rating_max))

    # Logique de Tri Fusionnée
    sort_by = request.GET.get('sort', 'date_desc')
    if sort_by == 'date_asc':
        drinks = drinks.order_by('date', 'id')
    elif sort_by == 'note_desc':
        drinks = drinks.order_by('-note', '-date')
    elif sort_by == 'note_asc':
        drinks = drinks.order_by('note', '-date')
    elif sort_by == 'name_asc':
        drinks = drinks.order_by('beer_id__name', '-date')
    elif sort_by == 'name_desc':
        drinks = drinks.order_by('-beer_id__name', '-date')
    elif sort_by == 'style_asc':
        drinks = drinks.order_by('beer_id__style', 'beer_id__name')
    elif sort_by == 'degree_desc':
        drinks = drinks.order_by('-beer_id__degree', 'beer_id__name')
    elif sort_by == 'degree_asc':
        drinks = drinks.order_by('beer_id__degree', 'beer_id__name')
    elif sort_by == 'ibu_desc':
        drinks = drinks.order_by('-beer_id__bitterness', 'beer_id__name')
    elif sort_by == 'ibu_asc':
        drinks = drinks.order_by('beer_id__bitterness', 'beer_id__name')
    else: # date_desc (défaut : dégustation récente)
        drinks = drinks.order_by('-date', '-id')

    return drinks

ACTIVITY_FRIENDS = 'friends'
ACTIVITY_MIXED = 'mixed'
ACTIVITY_COMMUNITY = 'community'


def _visible_tastings(user):
    """Dégustations notées, hors bières retirées, blocages et comptes suspendus ; visuels et auteurs préchargés (pas de requête par ligne)."""
    return (
        Drinks.objects.filter(beer_id__is_deleted=False, note__isnull=False)
        .exclude(drinker_id__in=get_excluded_users(user))
        .select_related('drinker_id', 'beer_id', 'beer_id__brewery_id')
        .prefetch_related('drinker_id__socialaccount_set')
        .order_by('-date', '-created_at', '-id')
    )


def _followed_ids(user):
    return user.following.values_list('followed_id', flat=True)


def _friends_tastings(user):
    return _visible_tastings(user).filter(drinker_id__in=_followed_ids(user))


def _community_tastings(user):
    """Tout le monde sauf moi et mes amis (les amis passent avant, sans doublon)."""
    return _visible_tastings(user).exclude(drinker_id=user).exclude(drinker_id__in=_followed_ids(user))


def get_activity(user, limit=10):
    """Fil d'activité : les dégustations des amis d'abord (les plus récentes), puis celles de la communauté pour compléter.

    Chaque dégustation reçoit `is_friend`. Une requête pour les amis, une seconde seulement s'il faut compléter.
    """
    friends = list(_friends_tastings(user)[:limit])
    missing = limit - len(friends)
    community = list(_community_tastings(user)[:missing]) if missing > 0 else []
    for tasting in friends:
        tasting.is_friend = True
    for tasting in community:
        tasting.is_friend = False
    return friends + community


def activity_kind(tastings):
    """« friends » si tout vient d'amis, « community » si rien, « mixed » sinon."""
    friends = sum(1 for tasting in tastings if tasting.is_friend)
    if friends == len(tastings) and friends:
        return ACTIVITY_FRIENDS
    return ACTIVITY_MIXED if friends else ACTIVITY_COMMUNITY


ACTIVITY_TITLES = {
    ACTIVITY_FRIENDS: "Vos amis ont goûté",
    ACTIVITY_MIXED: "Vos amis et la communauté",
    ACTIVITY_COMMUNITY: "La communauté a goûté",
}


def get_wishlist_beers(request):
    """Liste « À goûter » du membre, avec la même recherche et les mêmes tris que le catalogue.

    « Récentes » (défaut) classe selon la date d'ajout à la liste, pas selon la création de la bière.
    """
    beers = get_filtered_beers(request).filter(wishlisted_by=request.user)
    if request.GET.get('sort', 'date_desc') == 'date_desc':
        wished = BeerUser.wishlist_beers.through.objects.filter(beer_id=OuterRef('pk'), beeruser_id=request.user.pk)
        beers = beers.annotate(wished_id=Subquery(wished.values('id')[:1])).order_by('-wished_id', '-id')
    return beers
