from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Avg, Q, Count
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from ..forms import BeerForm, DrinkForm
from ..models import Beer, Drinks

@ensure_csrf_cookie
def index(request):
    month = timezone.now().month
    year = timezone.now().year
    
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
    rating_form = None

    if request.user.is_authenticated:
        drunk_beer_ids = Drinks.objects.filter(drinker_id=request.user).values_list('beer_id', flat=True)
        unrated_beers = Beer.objects.exclude(id__in=drunk_beer_ids).select_related('brewery_id')
        rating_form = DrinkForm()

    context = {
        "top": top10, 
        "topMonth": top10Month, 
        "unrated_beers": unrated_beers,
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
            new_beer = beer_form.save()
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