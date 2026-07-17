from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import Count, Case, When, Value, IntegerField, Avg, Q, Max, Prefetch
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from ..forms import DrinkForm
from ..models import Beer, Drinks, BeerSpot, UserFollow, BeerUser
from .utils import get_excluded_users, get_user_achievements

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
        
        liked_drinks = Drinks.objects.filter(drinker_id=request.user, note__gte=7)
        
        if liked_drinks.exists():
            # A. Récupération des préférences exactes
            pref_style = liked_drinks.exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values('beer_id__style').annotate(c=Count('id')).order_by('-c').first()
            pref_style_name = pref_style['beer_id__style'] if pref_style else None
            
            pref_brewery = liked_drinks.values('beer_id__brewery_id').annotate(c=Count('id')).order_by('-c').first()
            pref_brewery_id = pref_brewery['beer_id__brewery_id'] if pref_brewery else None

            # B. Récupération des moyennes (Tolérance Alcool & Amertume)
            averages = liked_drinks.aggregate(
                avg_ibu=Avg('beer_id__bitterness'),
                avg_deg=Avg('beer_id__degree')
            )
            avg_ibu = float(averages['avg_ibu'] or 0)
            avg_deg = float(averages['avg_deg'] or 0)

            # C. Calcul du score pondéré complet en base de données
            recommendations = unrated_beers.annotate(
                match_score=(
                    # 1. Style identique (+3 pts)
                    Case(When(style=pref_style_name, then=Value(3)), default=Value(0), output_field=IntegerField()) +
                    # 2. Brasserie identique (+2 pts)
                    Case(When(brewery_id=pref_brewery_id, then=Value(2)), default=Value(0), output_field=IntegerField()) +
                    # 3. Degré d'alcool similaire : +/- 1.5% (+1 pt)
                    Case(When(degree__range=(max(0, avg_deg - 1.5), avg_deg + 1.5), then=Value(1)), default=Value(0), output_field=IntegerField()) +
                    # 4. Amertume similaire : +/- 15 IBU (+1 pt)
                    Case(When(bitterness__range=(max(0, avg_ibu - 15), avg_ibu + 15), then=Value(1)), default=Value(0), output_field=IntegerField())
                )
            )
            
            # D. Filtrer (au moins 1 point), calculer la note globale de la communauté et trier
            recommended_beers = recommendations.filter(match_score__gt=0).annotate(
                global_rating=Avg('drinks__note')
            ).order_by('-match_score', '-global_rating')[:5]
        
        # Si on n'a pas de recommandations (nouveau compte ou pas assez de notes), on propose les meilleures bières globales non goûtées
        if not recommended_beers:
            recommended_beers = unrated_beers.annotate(
                global_rating=Avg('drinks__note')
            ).exclude(global_rating__isnull=True).order_by('-global_rating')[:5]
            
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
    
    context = {
        "unrated_beers": unrated_beers_display,
        "recommended_beers": recommended_beers,
        "rating_form": rating_form,
        "top": top,
        "topMonth": topMonth
    }
    return render(request, "home.html", context)
    
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
    if style_filter: beers = beers.filter(style__iexact=style_filter)

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
        drinks = drinks.filter(beer_id__style__iexact=style_filter)

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

@login_required(login_url='login')
def load_more_beers(request):
    """API pour charger les 10 bières suivantes."""
    offset = int(request.GET.get('offset', 0))
    limit = 10
    
    drunk_beer_ids = Drinks.objects.filter(drinker_id=request.user).values_list('beer_id', flat=True)
    unrated_beers = Beer.objects.filter(is_deleted=False).exclude(id__in=drunk_beer_ids).select_related('brewery_id', 'added_by')[offset:offset+limit]
    
    # S'il n'y a plus de bières à charger
    if not unrated_beers:
        return JsonResponse({'html': '', 'has_more': False})
    
    rating_form = DrinkForm()
    
    # On génère le HTML à partir du partial
    html = render_to_string(
        'partials/unrated_beers.html', 
        {'unrated_beers': unrated_beers, 'rating_form': rating_form}, 
        request=request
    )
    
    return JsonResponse({
        'html': html, 
        'has_more': len(unrated_beers) == limit # Vrai s'il y a probablement encore une page
    })
    
@login_required(login_url='login')
def load_more_search_beers(request):
    """API pour charger les 10 bières suivantes dans la recherche."""
    offset = int(request.GET.get('offset', 0))
    limit = 10
    beers = get_filtered_beers(request)[offset:offset+limit]
    
    if not beers:
        return JsonResponse({'html': '', 'has_more': False})
        
    rating_form = DrinkForm()
    rated_beer_ids = list(Drinks.objects.filter(drinker_id=request.user).values_list('beer_id', flat=True))
    
    html = render_to_string('partials/search_beers.html', {'beers': beers, 'rating_form': rating_form, 'rated_beer_ids': rated_beer_ids}, request=request)
    return JsonResponse({'html': html, 'has_more': len(beers) == limit})

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
    styles = Beer.objects.filter(is_deleted=False).exclude(style__isnull=True).exclude(style='').values_list('style', flat=True).distinct().order_by('style')
    rating_form = DrinkForm()
    rated_beer_ids = list(Drinks.objects.filter(drinker_id=request.user).values_list('beer_id', flat=True)) if request.user.is_authenticated else []

    user_query = request.GET.get('uq')
    active_tab = 'membres' if (user_query or request.GET.get('tab') == 'membres') else 'bieres'

    context = {
        'beers': beers,
        'rating_form': rating_form,
        'rated_beer_ids': rated_beer_ids,
        'users': users,
        'active_tab': active_tab,
        'styles': styles,
    }
    return render(request, 'all_beers.html', context)

@login_required(login_url='login')
def map_view(request):
    # Les abonnés de l'utilisateur (les gens qui LE suivent)
    followers = UserFollow.objects.filter(followed=request.user).select_related('follower')
    
    # Ses dégustations
    user_drinks = Drinks.objects.filter(drinker_id=request.user).select_related('beer_id').order_by('-date')
    
    if request.method == 'POST':
        spot_id = request.POST.get('spot_id') # S'il y a un ID, c'est une modification
        title = request.POST.get('title')
        description = request.POST.get('description')
        date_spot = request.POST.get('date', timezone.now().date())
        lat = request.POST.get('lat')
        lng = request.POST.get('lng')
        drink_ids = request.POST.getlist('drinks')
        friend_ids = request.POST.getlist('friends')
        
        if title and lat and lng:
            if spot_id:
                # --- MODE MODIFICATION ---
                spot = get_object_or_404(BeerSpot, id=spot_id)
                
                # Vérification des droits : Créateur OU Ami associé
                if request.user == spot.user or request.user in spot.friends.all():
                    spot.title = title
                    spot.description = description
                    spot.date = date_spot
                    spot.latitude = float(lat)
                    spot.longitude = float(lng)
                    spot.save()
                    
                    user_current_drinks = spot.drinks.filter(drinker_id=request.user)
                    spot.drinks.remove(*user_current_drinks)
                    if drink_ids:
                        # On identifie les bières déjà ajoutées par les autres sur ce point
                        beers_from_others = spot.drinks.exclude(drinker_id=request.user).values_list('beer_id', flat=True)
                        # On ne garde que les dégustations dont la bière n'est pas déjà présente
                        valid_drinks = Drinks.objects.filter(id__in=drink_ids).exclude(beer_id__in=beers_from_others)
                        spot.drinks.add(*valid_drinks)
                        
                    # Seul le créateur original peut gérer qui a accès au point
                    if request.user == spot.user:
                        spot.friends.set(friend_ids)
                        
                    messages.success(request, "Point modifié avec succès !")
                else:
                    messages.error(request, "Action non autorisée.")
            else:
                # --- MODE CRÉATION ---
                spot = BeerSpot.objects.create(
                    user=request.user,
                    title=title,
                    description=description,
                    date=date_spot,
                    latitude=float(lat),
                    longitude=float(lng)
                )
                if drink_ids:
                    spot.drinks.set(drink_ids)
                if friend_ids:
                    spot.friends.set(friend_ids)
                messages.success(request, "Point ajouté avec succès !")
                
        return redirect('map')

    # Récupérer : Mes propres lieux + Les lieux où je suis tagué comme ami
    user_spots = BeerSpot.objects.filter(
        Q(user=request.user) | Q(friends=request.user)
    ).exclude(user__in=get_excluded_users(request.user)).distinct().prefetch_related('drinks', 'drinks__beer_id', 'friends')

    context = {
        'user_drinks': user_drinks,
        'user_spots': user_spots,
        'followers': followers,
    }
    return render(request, 'map.html', context)

@login_required(login_url='login')
def load_more_notebook_drinks(request):
    """API pour charger les 10 dégustations suivantes du carnet."""
    offset = int(request.GET.get('offset', 0))
    limit = 10
    
    my_drinks = get_filtered_notebook_drinks(request)[offset:offset+limit]
    
    if not my_drinks:
        return JsonResponse({'html': '', 'has_more': False})
        
    # Génération du HTML à partir du nouveau partial
    html = render_to_string('partials/notebook_drinks.html', {'my_drinks': my_drinks}, request=request)
    
    return JsonResponse({'html': html, 'has_more': len(my_drinks) == limit})

@login_required(login_url='login')
def load_more_added_beers(request):
    """API pour charger les 10 bières proposées suivantes."""
    offset = int(request.GET.get('offset', 0))
    limit = 10
    user = request.user
    
    my_added_beers = Beer.objects.filter(added_by=user, is_deleted=False).annotate(
        user_note=Max('drinks__note', filter=Q(drinks__drinker_id=user))
    ).order_by('-id')[offset:offset+limit]
    
    if not my_added_beers:
        return JsonResponse({'html': '', 'has_more': False})
        
    html = render_to_string('partials/notebook_added_beers.html', {'my_added_beers': my_added_beers}, request=request)
    return JsonResponse({'html': html, 'has_more': len(my_added_beers) == limit})

@login_required(login_url='login')
def load_more_notebook_feedback(request):
    """API pour charger les 10 avis suivants sur les bières proposées."""
    offset = int(request.GET.get('offset', 0))
    limit = 10
    user = request.user
    
    feedback_on_my_beers = Drinks.objects.filter(beer_id__added_by=user).exclude(drinker_id=user).select_related('drinker_id', 'beer_id').order_by('-date')[offset:offset+limit]
    
    if not feedback_on_my_beers:
        return JsonResponse({'html': '', 'has_more': False})
        
    html = render_to_string('partials/notebook_feedback.html', {'feedback_on_my_beers': feedback_on_my_beers}, request=request)
    return JsonResponse({'html': html, 'has_more': len(feedback_on_my_beers) == limit})

@login_required(login_url='login')
def notebook_view(request):
    """Page du carnet de dégustation complet."""
    user = request.user
    
    # 1. Utilisation du Helper pour le carnet filtré
    my_drinks = get_filtered_notebook_drinks(request)[:10]
    
    # 2. Récupération des styles (uniquement les styles des bières que l'utilisateur a bues)
    styles = Drinks.objects.filter(drinker_id=user).exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values_list('beer_id__style', flat=True).distinct().order_by('beer_id__style')
    
    # Récupération des ajouts et suppressions de l'utilisateur
    my_added_beers = Beer.objects.filter(added_by=user, is_deleted=False).annotate(
        user_note=Max('drinks__note', filter=Q(drinks__drinker_id=user))
    ).order_by('-id')[:10]
    
    my_deleted_beers = Beer.objects.filter(added_by=user, is_deleted=True).annotate(
        user_note=Max('drinks__note', filter=Q(drinks__drinker_id=user))
    ).order_by('-id')
    
    # Avis des autres sur mes bières
    feedback_on_my_beers = Drinks.objects.filter(beer_id__added_by=user).exclude(drinker_id=user).select_related('drinker_id', 'beer_id').order_by('-date')[:10]

    active_tab = request.GET.get('tab', 'carnet')

    context = {
        'my_drinks': my_drinks,
        'styles': styles,
        'my_added_beers': my_added_beers,
        'my_deleted_beers': my_deleted_beers,
        'feedback_on_my_beers': feedback_on_my_beers,
        'active_tab': active_tab,
    }
    return render(request, 'notebook.html', context)

@login_required(login_url='login')
def achievements_view(request):
    """Page des trophées, hauts faits et cosmétiques."""
    achievements = get_user_achievements(request.user)
    return render(request, 'achievements.html', {'achievements': achievements})