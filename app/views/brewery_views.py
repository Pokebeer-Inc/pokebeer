from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from ..forms import DrinkForm, BreweryEditForm
from ..models import Beer, Drinks, Brewery, BeerUser, Notification
from ..services.realtime_service import broadcast_notifications

@login_required(login_url='login')
def brewery_detail_view(request, brewery_id):
    """Affiche les détails d'une brasserie et la liste de ses bières."""
    brewery = get_object_or_404(Brewery, id=brewery_id)
    beers = Beer.objects.filter(brewery_id=brewery, is_deleted=False).order_by('name')

    # Gestion des droits de la brasserie
    is_manager = False
    current_managers = []
    
    if request.user.is_authenticated:
        is_manager = brewery.managers.filter(id=request.user.id).exists()
        if is_manager:
            current_managers = brewery.managers.all()
            # On récupère tous les autres utilisateurs pour la barre de recherche

    # Limiter aux bières de cette brasserie
    rated_beer_ids = []
    wishlist_beer_ids = []
    if request.user.is_authenticated:
        displayed_ids = [b.id for b in beers]
        rated_beer_ids = list(Drinks.objects.filter(drinker_id=request.user, beer_id__in=displayed_ids).values_list('beer_id', flat=True))
        wishlist_beer_ids = list(request.user.wishlist_beers.filter(id__in=displayed_ids).values_list('id', flat=True))

    rating_form = DrinkForm()

    context = {
        'brewery': brewery,
        'beers': beers,
        'rated_beer_ids': rated_beer_ids,
        'wishlist_beer_ids': wishlist_beer_ids,
        'rating_form': rating_form,
        'is_manager': is_manager,
        'current_managers': current_managers,
        'other_users': [],
    }
    return render(request, 'brewery_page.html', context)

@login_required(login_url='login')
def edit_brewery_view(request, brewery_id):
    """Permet aux managers de modifier les informations de la brasserie."""
    brewery = get_object_or_404(Brewery, id=brewery_id)
    
    # Sécurité : Vérifier que l'utilisateur est bien manager
    if not brewery.managers.filter(id=request.user.id).exists():
        messages.error(request, "Vous n'avez pas l'autorisation de modifier cet établissement.")
        return redirect('brewery_detail', brewery_id=brewery.id)

    if request.method == 'POST':
        form = BreweryEditForm(request.POST, request.FILES, instance=brewery)
        if form.is_valid():
            form.save()
            
            other_managers = brewery.managers.exclude(id=request.user.id)
            if other_managers.exists():
                notifs = [Notification(recipient=m, sender=request.user, notif_type='place_updated', brewery=brewery) for m in other_managers]
                created_notifs = Notification.objects.bulk_create(notifs)
                broadcast_notifications(created_notifs)
                
            messages.success(request, "Les informations de la brasserie ont été mises à jour.")
            return redirect('brewery_detail', brewery_id=brewery.id)
    else:
        form = BreweryEditForm(instance=brewery)
        
    return render(request, 'edit_brewery.html', {'form': form, 'brewery': brewery})

@login_required(login_url='login')
def add_brewery_manager(request, brewery_id):
    """Ajoute un utilisateur comme collaborateur."""
    brewery = get_object_or_404(Brewery, id=brewery_id)
    
    if request.method == 'POST' and brewery.managers.filter(id=request.user.id).exists():
        user_id = request.POST.get('user_id')
        user_to_add = get_object_or_404(BeerUser, id=user_id)
        brewery.managers.add(user_to_add)
        
        notif = Notification.objects.create(recipient=user_to_add, sender=request.user, notif_type='manager_added', brewery=brewery)
        broadcast_notifications([notif])
            
        messages.success(request, f"{user_to_add.username} a été ajouté aux collaborateurs.")
        
    return redirect('brewery_detail', brewery_id=brewery.id)

@login_required(login_url='login')
def remove_brewery_manager(request, brewery_id, user_id):
    """Retire l'accès à un collaborateur (sauf soi-même)."""
    brewery = get_object_or_404(Brewery, id=brewery_id)
    
    if request.method == 'POST' and brewery.managers.filter(id=request.user.id).exists():
        if request.user.id != int(user_id): # Empêcher de se supprimer soi-même
            user_to_remove = get_object_or_404(BeerUser, id=user_id)
            brewery.managers.remove(user_to_remove)
            
            notif = Notification.objects.create(recipient=user_to_remove, sender=request.user, notif_type='manager_removed', text_content=brewery.name)
            broadcast_notifications([notif])
            
            messages.success(request, f"L'accès de {user_to_remove.username} a été retiré.")
            
    return redirect('brewery_detail', brewery_id=brewery.id)

from django.http import JsonResponse

@login_required(login_url='login')
def api_search_users_for_manager(request, brewery_id):
    """Recherche AJAX de collaborateurs, limitée à 10 résultats pour les performances"""
    query = request.GET.get('q', '').strip()
    brewery = get_object_or_404(Brewery, id=brewery_id)
    
    # Sécurité : Seul un manager peut chercher des collaborateurs
    if not brewery.managers.filter(id=request.user.id).exists():
        return JsonResponse({'error': 'Non autorisé'}, status=403)
        
    if len(query) < 2:
        return JsonResponse({'users': []})
        
    # On exclut ceux qui sont DÉJÀ managers
    existing_managers = brewery.managers.values_list('id', flat=True)
    
    # Recherche "icontains" (insensible à la casse) limitée à 10 résultats
    users = BeerUser.objects.filter(username__icontains=query).exclude(id__in=existing_managers)[:10]
    
    # On prépare les données avec l'URL de l'avatar (Google ou généré)
    data = []
    for u in users:
        # Avatar par défaut
        avatar_url = f"https://ui-avatars.com/api/?name={u.username}&background=E5A022&color=fff&bold=true"
        
        # Vérification du compte Google
        social_account = u.socialaccount_set.first()
        if social_account and social_account.extra_data.get('picture'):
            avatar_url = social_account.extra_data.get('picture')
            
        data.append({
            'id': u.id, 
            'username': u.username,
            'avatar_url': avatar_url
        })
    
    return JsonResponse({'users': data})
    
    return JsonResponse({'users': data})