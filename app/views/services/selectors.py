from django.db.models import Case, When, Value, IntegerField, Q, Max, Prefetch

from ...models import Beer, Drinks, BeerUser
from ..utils import get_excluded_users

def get_filtered_beers(request):
    """Extrait la logique de filtrage des bières pour la réutiliser."""
    beers = Beer.objects.filter(is_deleted=False).exclude(added_by__in=get_excluded_users(request.user)).select_related('brewery_id')

    query = request.GET.get('q')
    if query:
        beers = beers.filter(Q(name__icontains=query) | Q(brewery_id__name__icontains=query))

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

    order_fields = []
    
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
    user_query = request.GET.get('uq')
    
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
        users = users.filter(username__icontains=user_query)
    else:
        users = users.filter(added_beers__is_deleted=False).annotate(latest_beer_id=Max('added_beers__id')).order_by('-latest_beer_id')
        
    return users

def get_filtered_notebook_drinks(request):
    """Extrait la logique de filtrage des dégustations du carnet."""
    drinks = Drinks.objects.filter(drinker_id=request.user).select_related('beer_id', 'beer_id__brewery_id')
    
    # Filtrage par carnet personnalisé
    notebook_id = request.GET.get('notebook_id')
    if notebook_id and notebook_id.isdigit():
        drinks = drinks.filter(notebooks__id=int(notebook_id))

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

    rating_min = request.GET.get('rating_min')
    if rating_min and rating_min.isdigit():
        drinks = drinks.filter(note__gte=int(rating_min))
        
    rating_max = request.GET.get('rating_max')
    if rating_max and rating_max.isdigit():
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