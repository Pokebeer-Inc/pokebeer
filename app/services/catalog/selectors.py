from django.db.models import Case, When, Value, IntegerField, OuterRef, Q, Max, Prefetch, Count, Subquery, Exists

from ...models import Bar, Beer, BeerUser, Brewery, Drinks
from ..establishments import place_filters
from . import search
from ..establishments.places import BAR, BREWERY
from ..members.visibility import exclude_blocked, exclude_hidden_users


def search_query(request):
    """Texte de la barre de recherche unique (`q`) ; `uq` est l'ancien paramètre de la recherche de membres."""
    return (request.GET.get('q') or request.GET.get('uq') or '').strip()

# Filtres communs au catalogue et au carnet (degré, amertume, style) : un seul endroit pour les bornes et pour l'application
DEGREE_RANGES = {'light': {'lt': 5}, 'regular': {'gte': 5, 'lte': 8}, 'strong': {'gt': 8}}
IBU_RANGES = {'low': {'lt': 20}, 'medium': {'gte': 20, 'lte': 50}, 'high': {'gt': 50}}


def filter_by_beer_traits(queryset, params, prefix=''):
    """Applique ?degree=, ?ibu= et ?style= ; `prefix` désigne la bière quand le queryset est celui des dégustations (« beer__»)."""
    for param, field, ranges in (('degree', 'degree', DEGREE_RANGES), ('ibu', 'bitterness', IBU_RANGES)):
        bounds = ranges.get(params.get(param))
        if bounds:
            queryset = queryset.filter(**{f'{prefix}{field}__{operator}': value for operator, value in bounds.items()})
    style = params.get('style')
    if style:
        queryset = queryset.filter(**{f'{prefix}style__icontains': style})
    return queryset


# Tris proposés : clé du paramètre ?sort= -> champs de tri
BEER_SORTS = {
    'name_asc': ('name',), 'name_desc': ('-name',),
    'degree_desc': ('-degree', 'name'), 'degree_asc': ('degree', 'name'),
    'ibu_desc': ('-bitterness', 'name'), 'ibu_asc': ('bitterness', 'name'),
    'date_asc': ('id',), 'date_desc': ('-id',),
}
DRINK_SORTS = {
    'date_asc': ('date', 'id'), 'date_desc': ('-date', '-id'),
    'note_desc': ('-note', '-date'), 'note_asc': ('note', '-date'),
    'name_asc': ('beer__name', '-date'), 'name_desc': ('-beer__name', '-date'),
    'style_asc': ('beer__style', 'beer__name'),
    'degree_desc': ('-beer__degree', 'beer__name'), 'degree_asc': ('beer__degree', 'beer__name'),
    'ibu_desc': ('-beer__bitterness', 'beer__name'), 'ibu_asc': ('beer__bitterness', 'beer__name'),
}


def get_filtered_beers(request):
    """Extrait la logique de filtrage des bières pour la réutiliser."""
    # Bloqués seulement : le catalogue est partagé, les bières d'un compte suspendu restent visibles
    beers = exclude_blocked(Beer.objects.filter(is_deleted=False), request.user, 'added_by').select_related('brewery')

    query = search_query(request)
    beers = search.beers(beers, query)

    beers = filter_by_beer_traits(beers, request.GET)

    # Avec une recherche et sans tri choisi, les meilleures correspondances passent d'abord
    order_fields = [search.RANK_FIELD] if query and not request.GET.get('sort') else []
    
    # Logique de Tri : un tri inconnu ou absent donne le tri par défaut (non notées d'abord, puis les plus récentes)
    chosen = BEER_SORTS.get(request.GET.get('sort', 'unrated_first'))
    if chosen:
        order_fields.extend(chosen)
    else:
        if request.user.is_authenticated:
            # Les bières que le membre a déjà notées passent après : sous-requête SQL, aucun identifiant n'est chargé en mémoire
            rated = Drinks.objects.filter(drinker=request.user, beer=OuterRef('pk'))
            beers = beers.annotate(is_rated=Case(When(Exists(rated), then=Value(1)), default=Value(0), output_field=IntegerField()))
            order_fields.append('is_rated')

        # En second critère, on trie par les ajouts les plus récents
        order_fields.append('-id')

    beers = beers.order_by(*order_fields)
        
    return beers

def get_filtered_users(request):
    """Extrait la logique de filtrage des utilisateurs pour la réutiliser."""
    user_query = search_query(request)
    
    latest_beer_prefetch = Prefetch(
        'added_beers',
        queryset=Beer.objects.filter(is_deleted=False).select_related('brewery').order_by('-id'),
        to_attr='latest_beers_list'
    )
    
    users = exclude_blocked(BeerUser.objects.filter(is_active=True), request.user, 'id')
    if request.user.is_authenticated:
        users = users.exclude(id=request.user.id)
    users = users.prefetch_related(latest_beer_prefetch, 'socialaccount_set')
    
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
    drinks = Drinks.objects.filter(drinker=request.user).select_related('beer', 'beer__brewery')
    
    # Filtrage par carnet personnalisé
    notebook_slug = request.GET.get('notebook_slug')
    if notebook_slug:
        drinks = drinks.filter(notebooks__slug=notebook_slug)

    query = request.GET.get('q')
    if query:
        drinks = drinks.filter(Q(beer__name__icontains=query) | Q(beer__brewery__name__icontains=query))

    drinks = filter_by_beer_traits(drinks, request.GET, prefix='beer__')

    # Fourchette de notes : appliquée seulement si elle restreint (0-10 laisserait de côté les avis sans note)
    rating_min, rating_max = request.GET.get('rating_min', ''), request.GET.get('rating_max', '')
    if rating_min.isdigit() and int(rating_min) > 0:
        drinks = drinks.filter(note__gte=min(10, int(rating_min)))
    if rating_max.isdigit() and int(rating_max) < 10:
        drinks = drinks.filter(note__lte=int(rating_max))

    # Logique de Tri : un tri inconnu ou absent donne la dégustation la plus récente d'abord
    drinks = drinks.order_by(*DRINK_SORTS.get(request.GET.get('sort', 'date_desc'), DRINK_SORTS['date_desc']))

    return drinks

ACTIVITY_FRIENDS = 'friends'
ACTIVITY_MIXED = 'mixed'
ACTIVITY_COMMUNITY = 'community'


def _visible_tastings(user):
    """Dégustations notées, hors bières retirées, blocages et comptes suspendus ; visuels et auteurs préchargés (pas de requête par ligne)."""
    return (
        exclude_hidden_users(Drinks.objects.filter(beer__is_deleted=False, note__isnull=False), user, 'drinker')
        .select_related('drinker', 'beer', 'beer__brewery')
        .prefetch_related('drinker__socialaccount_set')
        .order_by('-date', '-created_at', '-id')
    )


def _followed_ids(user):
    return user.following.values_list('followed_id', flat=True)


def _friends_tastings(user):
    return _visible_tastings(user).filter(drinker__in=_followed_ids(user))


def _community_tastings(user):
    """Tout le monde sauf moi et mes amis (les amis passent avant, sans doublon)."""
    return _visible_tastings(user).exclude(drinker=user).exclude(drinker__in=_followed_ids(user))


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
        wished = BeerUser.wishlist_beers.through.objects.filter(beer=OuterRef('pk'), beeruser_id=request.user.pk)
        beers = beers.annotate(wished_id=Subquery(wished.values('id')[:1])).order_by('-wished_id', '-id')
    return beers
