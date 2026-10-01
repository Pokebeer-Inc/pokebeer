from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Q, Max

from ..forms import CustomNotebookForm, error_summary
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
def notebook_detail_view(request, notebook_slug=None):
    """Page d'un carnet spécifique (avec les filtres, le tri et la liste)."""
    user = request.user
    notebook = None
    notebook_drink_slugs = []
    
    if notebook_slug:
        notebook = get_object_or_404(CustomNotebook, slug=notebook_slug, user=user)
        # Injection du paramètre pour get_filtered_notebook_drinks
        request.GET = request.GET.copy()
        request.GET['notebook_slug'] = notebook.slug
        # Slugs des dégustations pour pré-cocher les cases
        notebook_drink_slugs = list(notebook.drinks.values_list('slug', flat=True))
        
    my_drinks = get_filtered_notebook_drinks(request)[:10]
    
    # Récupérer toutes les dégustations pour le formulaire de modification
    user_drinks_all = Drinks.objects.filter(drinker_id=user).select_related('beer_id').order_by('-date')
    
    if notebook:
        raw_styles = notebook.drinks.exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values_list('beer_id__style', flat=True)
    else:
        raw_styles = Drinks.objects.filter(drinker_id=user).exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values_list('beer_id__style', flat=True)
    
    unique_styles = set()
    for rs in raw_styles:
        unique_styles.update([s.strip() for s in rs.split(',') if s.strip()])
    styles = sorted(list(unique_styles))
    
    context = {
        'notebook': notebook,
        'my_drinks': my_drinks,
        'styles': styles,
        'user_drinks_all': user_drinks_all,
        'notebook_drink_slugs': notebook_drink_slugs,
    }
    return render(request, 'notebook_detail.html', context)

@require_POST
@login_required(login_url='login')
def create_custom_notebook(request):
    """Crée un nouveau carnet personnalisé."""
    if request.user.custom_notebooks.count() >= 50:
        messages.error(request, "Vous avez atteint la limite de 50 carnets.")
        return redirect('notebook')
        
    form = CustomNotebookForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Le carnet n'a pas pu être créé : " + " ; ".join(error_summary(form)))
        return redirect('notebook')

    notebook = form.save(commit=False)
    notebook.user = request.user
    notebook.save()
    drink_slugs = request.POST.getlist('drinks')
    if drink_slugs:
        notebook.drinks.set(Drinks.objects.filter(slug__in=drink_slugs, drinker_id=request.user))
    messages.success(request, "Carnet créé avec succès !")
        
    return redirect('notebook')

@require_POST
@login_required(login_url='login')
def delete_custom_notebook(request, notebook_slug):
    """Supprime un carnet personnalisé."""
    notebook = get_object_or_404(CustomNotebook, slug=notebook_slug, user=request.user)
    notebook.delete()
    messages.success(request, "Le carnet a été supprimé.")
    return redirect('notebook')

@require_POST
@login_required(login_url='login')
def edit_custom_notebook(request, notebook_slug):
    """Modifie le titre, la description et les bières d'un carnet personnalisé."""
    notebook = get_object_or_404(CustomNotebook, slug=notebook_slug, user=request.user)
    
    form = CustomNotebookForm(request.POST, instance=notebook)
    if not form.is_valid():
        messages.error(request, "Le carnet n'a pas pu être modifié : " + " ; ".join(error_summary(form)))
        return redirect('notebook_detail', notebook_slug=notebook.slug)

    form.save()
    notebook.drinks.set(Drinks.objects.filter(slug__in=request.POST.getlist('drinks'), drinker_id=request.user))
    messages.success(request, "Le carnet a été modifié avec succès.")
        
    return redirect('notebook_detail', notebook_slug=notebook.slug)
