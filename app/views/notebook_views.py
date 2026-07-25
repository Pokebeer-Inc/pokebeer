from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import Q, Max

from ..models import Beer, Drinks, CustomNotebook
from .services.selectors import get_filtered_notebook_drinks

@login_required(login_url='login')
def notebook_view(request):
    """Page racine listant les tuiles des carnets (et ajouts)."""
    user = request.user
    
    # Vérifie si l'utilisateur a au moins une dégustation pour l'empty state
    user_drinks_all = Drinks.objects.filter(drinker_id=user).select_related('beer_id').order_by('-date')
    has_drinks = user_drinks_all.exists()
    
    custom_notebooks = CustomNotebook.objects.filter(user=user)
    
    # Récupération des ajouts et suppressions de l'utilisateur (inchangé)
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
        'has_drinks': has_drinks,
        'user_drinks_all': user_drinks_all,
        'custom_notebooks': custom_notebooks,
        'my_added_beers': my_added_beers,
        'my_deleted_beers': my_deleted_beers,
        'feedback_on_my_beers': feedback_on_my_beers,
        'active_tab': active_tab,
    }
    return render(request, 'notebook.html', context)

@login_required(login_url='login')
def notebook_detail_view(request, notebook_id=None):
    """Page d'un carnet spécifique (avec les filtres, le tri et la liste)."""
    user = request.user
    notebook = None
    notebook_drink_ids = []
    
    if notebook_id:
        notebook = get_object_or_404(CustomNotebook, id=notebook_id, user=user)
        # Injection du paramètre pour get_filtered_notebook_drinks
        request.GET = request.GET.copy()
        request.GET['notebook_id'] = str(notebook.id)
        # Liste des IDs des dégustations pour pré-cocher les cases
        notebook_drink_ids = list(notebook.drinks.values_list('id', flat=True))
        
    my_drinks = get_filtered_notebook_drinks(request)[:10]
    
    # Récupérer toutes les dégustations pour le formulaire de modification
    user_drinks_all = Drinks.objects.filter(drinker_id=user).select_related('beer_id').order_by('-date')
    
    if notebook:
        styles = notebook.drinks.exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values_list('beer_id__style', flat=True).distinct().order_by('beer_id__style')
    else:
        styles = Drinks.objects.filter(drinker_id=user).exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values_list('beer_id__style', flat=True).distinct().order_by('beer_id__style')

    context = {
        'notebook': notebook,
        'my_drinks': my_drinks,
        'styles': styles,
        'user_drinks_all': user_drinks_all,
        'notebook_drink_ids': notebook_drink_ids,
    }
    return render(request, 'notebook_detail.html', context)

@require_POST
@login_required(login_url='login')
def create_custom_notebook(request):
    """Crée un nouveau carnet personnalisé."""
    if request.user.custom_notebooks.count() >= 50:
        messages.error(request, "Vous avez atteint la limite de 50 carnets.")
        return redirect('notebook')
        
    title = request.POST.get('title')
    description = request.POST.get('description')
    drink_ids = request.POST.getlist('drinks')
    
    if title:
        notebook = CustomNotebook.objects.create(user=request.user, title=title, description=description)
        if drink_ids:
            valid_drinks = Drinks.objects.filter(id__in=drink_ids, drinker_id=request.user)
            notebook.drinks.set(valid_drinks)
        messages.success(request, "Carnet créé avec succès !")
        
    return redirect('notebook')

@require_POST
@login_required(login_url='login')
def delete_custom_notebook(request, notebook_id):
    """Supprime un carnet personnalisé."""
    notebook = get_object_or_404(CustomNotebook, id=notebook_id, user=request.user)
    notebook.delete()
    messages.success(request, "Le carnet a été supprimé.")
    return redirect('notebook')

@require_POST
@login_required(login_url='login')
def edit_custom_notebook(request, notebook_id):
    """Modifie le titre, la description et les bières d'un carnet personnalisé."""
    notebook = get_object_or_404(CustomNotebook, id=notebook_id, user=request.user)
    
    title = request.POST.get('title')
    description = request.POST.get('description')
    drink_ids = request.POST.getlist('drinks')
    
    if title:
        notebook.title = title
        notebook.description = description
        notebook.save()
        
        valid_drinks = Drinks.objects.filter(id__in=drink_ids, drinker_id=request.user)
        notebook.drinks.set(valid_drinks)
        
        messages.success(request, "Le carnet a été modifié avec succès.")
        
    return redirect('notebook_detail', notebook_id=notebook.id)

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