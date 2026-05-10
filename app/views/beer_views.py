from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Case, When, Value, IntegerField, Avg, Q, Max, Prefetch
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from ..forms import BeerForm, DrinkForm
from ..models import Beer, Drinks, BeerSpot, UserFollow, BeerUser

@ensure_csrf_cookie
@login_required(login_url='login')
def index(request):
    # Bières non notées
    unrated_beers = []
    recommended_beers = []
    rating_form = None

    if request.user.is_authenticated:
        drunk_beer_ids = Drinks.objects.filter(drinker_id=request.user).values_list('beer_id', flat=True)
        unrated_beers = Beer.objects.filter(is_deleted=False).exclude(id__in=drunk_beer_ids).select_related('brewery_id')
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

    context = {
        "unrated_beers": unrated_beers,
        "recommended_beers": recommended_beers,
        "rating_form": rating_form,
        "top": top,
        "topMonth": topMonth
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
    """Traite la notation depuis n'importe quelle page"""
    beer = get_object_or_404(Beer, id=beer_id)
    
    previous_url = request.META.get('HTTP_REFERER', 'index')
    
    if Drinks.objects.filter(drinker_id=request.user, beer_id=beer).exists():
        messages.warning(request, f"Vous avez déjà noté la bière {beer.name}.")
        return redirect(previous_url)
    
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
            
    return redirect(previous_url)

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

@login_required(login_url='login')
def all_beers_view(request):
    """Affiche toutes les bières et tous les membres avec système d'onglets."""
    # ==========================
    # 1. LOGIQUE ONGLET BIÈRES
    # ==========================
    beers = Beer.objects.filter(is_deleted=False).select_related('brewery_id').all().order_by('name')

    query = request.GET.get('q')
    if query:
        beers = beers.filter(
            Q(name__icontains=query) | 
            Q(brewery_id__name__icontains=query)
        )

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
        
    #Filtre par Style
    style_filter = request.GET.get('style')
    if style_filter:
        beers = beers.filter(style__iexact=style_filter)

    # Récupérer tous les styles uniques (non vides) pour le menu déroulant
    styles = Beer.objects.filter(is_deleted=False).exclude(style__isnull=True).exclude(style='').values_list('style', flat=True).distinct().order_by('style')

    rating_form = DrinkForm()
    rated_beer_ids = []
    
    if request.user.is_authenticated:
        rated_beer_ids = list(Drinks.objects.filter(drinker_id=request.user).values_list('beer_id', flat=True))
        if rated_beer_ids:
            beers = beers.annotate(
                is_rated=Case(
                    When(id__in=rated_beer_ids, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField()
                )
            ).order_by('is_rated', 'name')

    # ==========================
    # 2. LOGIQUE ONGLET MEMBRES
    # ==========================
    user_query = request.GET.get('uq')
    
    # On précharge la toute dernière bière ajoutée par chaque utilisateur
    latest_beer_prefetch = Prefetch(
        'added_beers',
        queryset=Beer.objects.filter(is_deleted=False).select_related('brewery_id').order_by('-id'),
        to_attr='latest_beers_list'
    )
    
    users = BeerUser.objects.filter(is_superuser=False).exclude(id=request.user.id).prefetch_related(
        latest_beer_prefetch, 'socialaccount_set'
    )
    
    if user_query:
        # Si recherche active, on cherche le pseudo
        users = users.filter(username__icontains=user_query)[:30]
    else:
        # Par défaut : Utilisateurs ayant ajouté une bière, triés par le dernier ajout
        users = users.filter(added_beers__is_deleted=False).annotate(
            latest_beer_id=Max('added_beers__id')
        ).order_by('-latest_beer_id')[:30]

    # Déterminer quel onglet laisser ouvert au chargement de la page
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
        rating_from = DrinkForm()
        rating_from.fields['date'].initial = user_drink.date
        rating_from.fields['note'].initial = user_drink.note
        rating_from.fields['comment'].initial = user_drink.comment
    else:
        rating_from = DrinkForm()

    context = {
        'beer': beer,
        'drinks': drinks,
        'user_rating': user_rating,
        'rating_form': rating_from
    }

    return render(request, 'beer_page.html', context)

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
    ).distinct().prefetch_related('drinks', 'drinks__beer_id', 'friends')

    context = {
        'user_drinks': user_drinks,
        'user_spots': user_spots,
        'followers': followers,
    }
    return render(request, 'map.html', context)

@login_required(login_url='login')
def delete_drink_view(request, drink_id):
    """Permet de supprimer sa propre note."""
    drink = get_object_or_404(Drinks, id=drink_id, drinker_id=request.user)
    if request.method == 'POST':
        drink.delete()
        messages.success(request, "Votre dégustation a bien été supprimée.")
    return redirect(request.META.get('HTTP_REFERER', 'account'))

@login_required(login_url='login')
def delete_spot_view(request, spot_id):
    """Permet au propriétaire de supprimer son spot sur la carte."""
    spot = get_object_or_404(BeerSpot, id=spot_id, user=request.user)
    if request.method == 'POST':
        spot.delete()
        messages.success(request, "Lieu supprimé de la carte.")
    return redirect('map')

@login_required(login_url='login')
def edit_beer_view(request, beer_slug):
    """Éditer les infos d'une bière qu'on a proposée."""
    beer = get_object_or_404(Beer, slug=beer_slug, added_by=request.user, is_deleted=False)
    if request.method == 'POST':
        form = BeerForm(request.POST, request.FILES, instance=beer)
        if form.is_valid():
            form.save()
            messages.success(request, "Les informations de la bière ont été mises à jour.")
            return redirect('beer_detail', beer_slug=beer.slug)
    else:
        form = BeerForm(instance=beer)
    return render(request, 'edit_beer.html', {'form': form, 'beer': beer})

@login_required(login_url='login')
def delete_beer_view(request, beer_slug):
    """Soft-delete d'une bière du catalogue."""
    beer = get_object_or_404(Beer, slug=beer_slug, added_by=request.user, is_deleted=False)
    if request.method == 'POST':
        beer.is_deleted = True
        beer.save()
        messages.success(request, "Bière retirée du catalogue. Vos notes personnelles sont conservées.")
        return redirect('index')
    return redirect('beer_detail', beer_slug=beer.slug)