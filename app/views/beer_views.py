from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Case, When, Value, IntegerField, Avg, Q
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from ..forms import BeerForm, DrinkForm
from ..models import Beer, Drinks

@ensure_csrf_cookie
@login_required(login_url='login')
def index(request):
    month = timezone.now().month
    year = timezone.now().year
    user = request.user
    
    # Tops
    top10 = Beer.objects.annotate(
        avg_rating=Avg('drinks__note'),
        count_rating=Count('drinks')  # Compte total
    ).order_by('-avg_rating')[:10]
    
    top10Month = Beer.objects.annotate(
            avg_rating=Avg('drinks__note', filter=Q(drinks__date__year=year, drinks__date__month=month)),
            count_rating=Count('drinks', filter=Q(drinks__date__year=year, drinks__date__month=month)) # Compte filtré par mois
        ).filter(avg_rating__isnull=False).order_by('-avg_rating')[:10]
    
    # Bières non notées
    unrated_beers = []
    recommended_beers = []
    rating_form = None

    if request.user.is_authenticated:
        drunk_beer_ids = Drinks.objects.filter(drinker_id=request.user).values_list('beer_id', flat=True)
        unrated_beers = Beer.objects.exclude(id__in=drunk_beer_ids).select_related('brewery_id')
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

    context = {
        "top": top10, 
        "topMonth": top10Month, 
        "unrated_beers": unrated_beers,
        "recommended_beers": recommended_beers,
        "rating_form": rating_form
    }
    return render(request, "home.html", context)


@login_required(login_url='login')
def add_beer_view(request):
    """Crée une bière ET ajoute une première note automatiquement."""
    if request.method == 'POST':
        beer_form = BeerForm(request.POST, prefix='beer')
        drink_form = DrinkForm(request.POST, prefix='drink')
        
        if beer_form.is_valid() and drink_form.is_valid():
            new_beer = beer_form.save(user=request.user)
            new_drink = drink_form.save(commit=False)
            new_drink.drinker_id = request.user
            new_drink.beer_id = new_beer
            new_drink.save()
            
            messages.success(request, f"Bière ajoutée et notée ! Merci {request.user.username}.")
            return redirect('index')
        else:
            messages.error(request, "Erreur dans le formulaire. Veuillez vérifier les champs.")
    else:
        beer_form = BeerForm(prefix='beer')
        drink_form = DrinkForm(prefix='drink')

    context = {
        'beer_form': beer_form, 
        'drink_form': drink_form
    }
    return render(request, 'add_beer.html', context)


@login_required(login_url='login')
def rate_beer_view(request, beer_id):
    """Traite la notation depuis la home page"""
    beer = get_object_or_404(Beer, id=beer_id)
    
    if Drinks.objects.filter(drinker_id=request.user, beer_id=beer).exists():
        messages.warning(request, f"Vous avez déjà noté la bière {beer.name}.")
        return redirect('all_beers')
    
    if request.method == 'POST':
        form = DrinkForm(request.POST)
        if form.is_valid():
            drink = form.save(commit=False)
            drink.drinker_id = request.user
            drink.beer_id = beer
            drink.save()
            messages.success(request, f"Votre avis sur {beer.name} a été enregistré !")
        else:
            messages.error(request, "Erreur dans le formulaire de notation.")
            
    return redirect('index')

@login_required(login_url='login')
def modify_rate_beer_view(request, drink_id):
    """Permet de modifier une note depuis la page de détail d'une bière"""
    drink = get_object_or_404(Drinks, id=drink_id, drinker_id=request.user)
    beer = drink.beer_id
    
    if request.method == 'POST':
        form = DrinkForm(request.POST, instance=drink)
        if form.is_valid():
            form.save()
            messages.success(request, f"Votre avis sur {beer.name} a été mis à jour !")
        else:
            messages.error(request, "Erreur dans le formulaire de modification.")
            
    return redirect('beer_detail', beer_slug=beer.slug)


def all_beers_view(request):
    """Affiche toutes les bières avec recherche et filtres."""
    beers = Beer.objects.select_related('brewery_id').all().order_by('name')

    # Recherche
    query = request.GET.get('q')
    if query:
        beers = beers.filter(
            Q(name__icontains=query) | 
            Q(brewery_id__name__icontains=query)
        )

    # Filtres
    degree_filter = request.GET.get('degree')
    if degree_filter == 'light':
        beers = beers.filter(degree__lt=5)
    elif degree_filter == 'regular':
        beers = beers.filter(degree__gte=5, degree__lte=8)
    elif degree_filter == 'strong':
        beers = beers.filter(degree__gt=8)

    ibu_filter = request.GET.get('ibu')
    if ibu_filter == 'low':
        beers = beers.filter(bitterness__lt=20)
    elif ibu_filter == 'medium':
        beers = beers.filter(bitterness__gte=20, bitterness__lte=50)
    elif ibu_filter == 'high':
        beers = beers.filter(bitterness__gt=50)

    rating_form = DrinkForm()
    
    rated_beer_ids = []
    if request.user.is_authenticated:
        rated_beer_ids = list(Drinks.objects.filter(drinker_id=request.user).values_list('beer_id', flat=True))

    context = {
        'beers': beers,
        'rating_form': rating_form,
        'rated_beer_ids': rated_beer_ids,
    }
    return render(request, 'all_beers.html', context)

def beer_detail_view(request, beer_slug):
    """Affiche les détails d'une bière, ses notes et commentaires."""
    beer = get_object_or_404(Beer, slug=beer_slug)
    drinks = Drinks.objects.filter(beer_id=beer).select_related('drinker_id').order_by('-date')

    user_rating = None
    user_drink = drinks.filter(drinker_id=request.user).first() if request.user.is_authenticated else None
    if user_drink:
        user_rating = {
            'note': user_drink.note,
            'comment': user_drink.comment,
            'date': user_drink.date,
            'id': user_drink.id
        }

    context = {
        'beer': beer,
        'drinks': drinks,
        'user_rating': user_rating
    }

    return render(request, 'beer_page.html', context)