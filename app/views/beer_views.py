from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, F

from ..forms import BeerForm, DrinkForm, clear_invalid_fields, error_summary
from ..models import Beer, BeerDraft, Drinks, Notification, UserFollow, DrinkReaction
from ..services.members.achievements import check_and_notify_achievements
from ..services.members.visibility import exclude_hidden_users
from .utils import posted_notebooks
from ..services.catalog import beer_drafts
from ..services.messaging.notifications import notify
from ..services.protection.throttle import BEER_DRAFT_SAVES
from ..services.moderation.content import CONTENT_TYPES
from ..services.moderation.suggestions import menu_context as suggestion_menu

def _save_new_beer(user, beer_form, drink_form):
    """Enregistre la bière et sa première note ensemble. Renvoie False si le nom a été pris entre-temps."""
    try:
        with transaction.atomic():
            new_beer = beer_form.save(user=user)
            new_drink = drink_form.save(commit=False)
            new_drink.drinker = user
            new_drink.beer = new_beer
            new_drink.save()
    except IntegrityError:
        beer_form.instance.pk = None
        return False
    return True

def _draft_initial(draft):
    """Valeurs de départ des deux formulaires, tirées du brouillon (clés sans préfixe, comme les champs)."""
    beer_initial, drink_initial = {}, {}
    for key, value in (draft.data if draft else {}).items():
        prefix, _, name = key.partition('-')
        (beer_initial if prefix == 'beer' else drink_initial)[name] = value
    return beer_initial, drink_initial


@login_required(login_url='login')
def add_beer_view(request):
    """Ajoute une bière ET sa première note, par étapes : chaque étape validée est conservée dans un brouillon.

    L'envoi final est exactement celui d'avant (mêmes formulaires, mêmes champs obligatoires) ; les étapes n'existent que dans la page.
    """
    if request.method == 'POST':
        beer_form = BeerForm(request.POST, request.FILES, prefix='beer', user=request.user)
        drink_form = DrinkForm(request.POST, request.FILES, prefix='drink', user=request.user)
        
        notebooks = posted_notebooks(request)
        forms_valid = beer_form.is_valid() & drink_form.is_valid()  # & : valide les deux pour afficher toutes les erreurs

        if forms_valid and not _save_new_beer(request.user, beer_form, drink_form):
            # Course entre deux ajouts simultanés : la contrainte d'unicité en base a le dernier mot
            beer_form.add_error('name', "Cette bière vient d'être ajoutée par quelqu'un d'autre.")
            forms_valid = False

        if forms_valid:
            new_beer, new_drink = beer_form.instance, drink_form.instance
            
            for notebook in notebooks:
                notebook.drinks.add(new_drink)
            
            # Trouve tous mes abonnés
            followers = UserFollow.objects.filter(followed=request.user).values_list('follower_id', flat=True)
            # Création en masse
            notify('beer_added', followers, sender=request.user, beer=new_beer)
            
            if new_beer.brewery:
                # Le créateur n'est pas notifié s'il est lui-même manager (la politique d'envoi écarte l'auto-notification)
                notify('beer_added_to_brewery', new_beer.brewery.managers.all(), sender=request.user, beer=new_beer)
            
            check_and_notify_achievements(request.user)
            BeerDraft.objects.filter(user=request.user).delete()  # la bière existe : le brouillon n'a plus lieu d'être
            return redirect('add_beer_done', beer_slug=new_beer.slug)

        messages.error(request, "La bière n'a pas pu être ajoutée. Les champs en rouge ont été vidés : " + " ; ".join(error_summary(beer_form, drink_form)))
        start_step = beer_drafts.first_step_with_errors(beer_form, drink_form)  # on rouvre l'étape à corriger
        clear_invalid_fields(beer_form)
        clear_invalid_fields(drink_form)
        return render(request, 'add_beer.html', {
            'beer_form': beer_form,
            'drink_form': drink_form,
            'current_drink': {'notebook_slugs': [notebook.slug for notebook in notebooks]},
            'start_step': start_step, 'steps': beer_drafts.STEPS,
        })

    # Une bière demandée depuis la page d'une brasserie (?brewery=) repart de zéro ; sinon on reprend le brouillon du membre
    draft = None if request.GET.get('brewery') else beer_drafts.get_draft(request.user)
    beer_initial, drink_initial = _draft_initial(draft)
    if not draft:
        beer_initial['brewery_name'] = request.GET.get('brewery', '')
    context = {
        'beer_form': BeerForm(prefix='beer', initial=beer_initial, user=request.user),
        'drink_form': DrinkForm(prefix='drink', initial=drink_initial),
        'current_drink': {'notebook_slugs': draft.data.get('notebooks', [])} if draft else None,
        'start_step': draft.current_step if draft else 1,
        'resumed': bool(draft and draft.data),
        'draft_name': draft.data.get('beer-name', '') if draft else '',
        'steps': beer_drafts.STEPS,
    }
    return render(request, 'add_beer.html', context)


@require_POST
@login_required(login_url='login')
def save_beer_draft_view(request):
    """Enregistre une étape du brouillon.

    `strict=1` (bouton Suivant) : l'étape est validée par les formulaires de la page, rien n'est conservé si elle est refusée ;
    `strict=0` (retour, fermeture de la page) : on conserve ce qui est là sans rien valider. Réponse JSON, sauf 204 sans contenu en mode souple.
    """
    # Taille annoncée du corps (le corps lui-même n'est plus lisible une fois le formulaire analysé)
    declared = request.META.get('CONTENT_LENGTH', '')
    if not declared.isdecimal() or int(declared) > 20000:
        return JsonResponse({'ok': False, 'errors': ["Envoi trop volumineux."]}, status=413)
    if BEER_DRAFT_SAVES.exceeded(request.user.pk):
        return JsonResponse({'ok': False, 'errors': ["Trop d'enregistrements. Réessayez dans quelques minutes."]}, status=429)
    BEER_DRAFT_SAVES.record(request.user.pk)

    step = request.POST.get('step', '')
    if not step.isdecimal() or not 1 <= int(step) <= beer_drafts.LAST_STEP:
        return JsonResponse({'ok': False, 'errors': ["Étape inconnue."]}, status=400)
    step = int(step)

    if request.POST.get('strict') != '1':
        beer_drafts.save_lenient(request.user, request.POST, step)
        return HttpResponse(status=204)

    draft = beer_drafts.get_draft(request.user)
    result = beer_drafts.validate_step(request.user, step, request.POST, draft)
    if result['errors']:
        return JsonResponse({'ok': False, **result}, status=400)
    beer_drafts.save_lenient(request.user, request.POST, min(step + 1, beer_drafts.LAST_STEP))
    return JsonResponse({'ok': True})


@require_POST
@login_required(login_url='login')
def discard_beer_draft_view(request):
    """Recommencer : efface le brouillon du membre."""
    BeerDraft.objects.filter(user=request.user).delete()
    return redirect('add_beer')


@login_required(login_url='login')
def add_beer_done_view(request, beer_slug):
    """Page de félicitations après l'ajout d'une bière (réservée à la personne qui vient de l'ajouter)."""
    beer = get_object_or_404(Beer.objects.select_related('brewery'), slug=beer_slug, added_by=request.user, is_deleted=False)
    return render(request, 'add_beer_done.html', {
        'beer': beer,
        'beers_added': Beer.objects.filter(added_by=request.user, is_deleted=False).count(),
    })

@login_required(login_url='login')
def beer_detail_view(request, beer_slug):
    """Affiche les détails d'une bière, ses notes et commentaires."""
    beer = get_object_or_404(Beer, slug=beer_slug)
    
    # Calcul du Score (Likes - Dislikes) et Tri : les avis sont lus une seule fois, tout le reste (moyenne, avis du membre,
    # réactions) en est déduit sans requête supplémentaire
    drinks = list(exclude_hidden_users(Drinks.objects.filter(beer=beer), request.user, 'drinker').select_related('drinker').annotate(
        likes=Count('reactions', filter=Q(reactions__is_like=True)),
        dislikes=Count('reactions', filter=Q(reactions__is_like=False))
    ).annotate(
        score=F('likes') - F('dislikes')
    ).order_by('-score', '-date'))

    # Identifier les réactions de l'utilisateur connecté pour l'UI
    user_reactions = {}
    if request.user.is_authenticated:
        reactions = DrinkReaction.objects.filter(user=request.user, drink_id__in=[drink.id for drink in drinks]).values_list('drink_id', 'is_like')
        user_reactions = {r[0]: r[1] for r in reactions}

    for drink in drinks:
        drink.user_reaction = user_reactions.get(drink.id, None)

    # Format
    user_rating = None
    user_drink = next((drink for drink in drinks if drink.drinker_id == request.user.pk), None)
    if user_drink:
        user_rating = {
            'note': user_drink.note,
            'comment': user_drink.comment,
            'photo_url': user_drink.photo_url,
            'date': user_drink.date,
            'slug': user_drink.slug,
            'likes': getattr(user_drink, 'likes', 0),
            'dislikes': getattr(user_drink, 'dislikes', 0),
            'notebook_slugs': list(user_drink.notebooks.values_list('slug', flat=True)),
            'venue_type': user_drink.venue_type,
            'company': user_drink.company,
            'serving_format': user_drink.serving_format,
            'price': user_drink.price,
            'context': ' · '.join(part for part in (
                user_drink.get_venue_type_display(), user_drink.get_company_display(), user_drink.get_serving_format_display(),
                f"{user_drink.price:.2f} €".replace('.', ',') if user_drink.price is not None else '') if part),
        }
        rating_from = DrinkForm()
        rating_from.fields['date'].initial = user_drink.date
        rating_from.fields['note'].initial = user_drink.note
        rating_from.fields['comment'].initial = user_drink.comment
    else:
        rating_from = DrinkForm()

    wishlist_beer_ids = []
    is_brewery_manager = False # NOUVEAU
    
    if request.user.is_authenticated:
        if request.user.wishlist_beers.filter(id=beer.id).exists():
            wishlist_beer_ids.append(beer.id)
            
        # On vérifie si le user est manager de la brasserie liée à cette bière
        if beer.brewery:
            is_brewery_manager = beer.brewery.managers.filter(id=request.user.id).exists()

    notes = [drink.note for drink in drinks if drink.note is not None]
    average = {'average': sum(notes) / len(notes) if notes else None, 'count': len(notes)}

    context = {
        'beer': beer,
        'drinks': drinks,
        'average_note': average['average'],
        'rating_count': average['count'],
        'is_brewery_manager': is_brewery_manager,
        'user_rating': user_rating,
        'rating_form': rating_from,
        'wishlist_beer_ids': wishlist_beer_ids,
        **suggestion_menu(CONTENT_TYPES['beer'], beer, request.user),
    }
    return render(request, 'beer_page.html', context)

@login_required(login_url='login')
def edit_beer_view(request, beer_slug):
    """Éditer les infos d'une bière qu'on a proposée ou dont on gère la brasserie."""
    
    beer = get_object_or_404(Beer, slug=beer_slug, is_deleted=False)
    
    # Vérification des droits : le gérant de la brasserie, ou le créateur tant que le staff n'a pas vérifié la fiche
    is_creator = (beer.added_by == request.user)
    is_manager = beer.brewery and beer.brewery.managers.filter(id=request.user.id).exists()
    
    if not (is_manager or (is_creator and not beer.is_verified)):
        messages.error(request, "Cette fiche est vérifiée : seul le gérant de la brasserie peut la modifier." if is_creator else "Vous n'avez pas l'autorisation de modifier cette bière.")
        return redirect('beer_detail', beer_slug=beer.slug)

    if request.method == 'POST':
        form = BeerForm(request.POST, request.FILES, instance=beer, user=request.user)
        if form.is_valid():
            form.save()
            
            drinkers = Drinks.objects.filter(beer=beer).exclude(drinker=request.user).values_list('drinker', flat=True).distinct()
            
            notify('beer_updated', drinkers, sender=request.user, beer=beer)
            
            if is_manager and not is_creator and beer.added_by:
                notify('beer_updated_by_manager', [beer.added_by], sender=request.user, beer=beer)
                
            messages.success(request, "Les informations de la bière ont été mises à jour.")
            return redirect('beer_detail', beer_slug=beer.slug)
    else:
        form = BeerForm(instance=beer, user=request.user)
    return render(request, 'edit_beer.html', {'form': form, 'beer': beer})

@login_required(login_url='login')
def delete_beer_view(request, beer_slug):
    """Soft-delete d'une bière du catalogue."""
    
    beer = get_object_or_404(Beer, slug=beer_slug, is_deleted=False)
    
    # Vérification des droits
    is_creator = (beer.added_by == request.user)
    is_manager = beer.brewery and beer.brewery.managers.filter(id=request.user.id).exists()
    
    if not (is_creator or is_manager):
        messages.error(request, "Vous n'avez pas l'autorisation de retirer cette bière.")
        return redirect('beer_detail', beer_slug=beer.slug)

    if request.method == 'POST':
        beer.is_deleted = True
        beer.save()
        
        # Supprimer les notifications liées à cette bière
        Notification.objects.filter(beer=beer).delete()
        
        if beer.added_by:
            check_and_notify_achievements(beer.added_by)
        
        if is_manager and not is_creator and beer.added_by:
            # On utilise le texte libre car la bière est désormais cachée
            notify('beer_deleted_by_manager', [beer.added_by], sender=request.user, text_content=beer.name)
        
        messages.success(request, "Bière retirée du catalogue. Vos notes personnelles sont conservées.")
        return redirect('index')
    return redirect('beer_detail', beer_slug=beer.slug)
