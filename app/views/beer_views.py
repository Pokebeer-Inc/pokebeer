from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Avg, Count

from ..forms import BeerForm, DrinkForm, clear_invalid_fields, error_summary
from ..models import Beer, BeerDraft, Drinks
from ..services.catalog.selectors import beer_reviews, visible_tastings_of, with_reaction_counts
from .utils import posted_notebooks
from ..services.catalog import beer_drafts, beers, permissions
from ..services.protection.throttle import BEER_DRAFT_SAVES
from ..services.tracking import page_views
from ..services.moderation.content import CONTENT_TYPES
from ..services.moderation.suggestions import menu_context as suggestion_menu

def _draft_initial(draft):
    """Valeurs de départ des deux formulaires, tirées du brouillon (clés sans préfixe, comme les champs)."""
    beer_initial, drink_initial = {}, {}
    for key, value in (draft.data if draft else {}).items():
        prefix, _, name = key.partition('-')
        (beer_initial if prefix == 'beer' else drink_initial)[name] = value
    return beer_initial, drink_initial


def add_beer_view(request):
    """Ajoute une bière ET sa première note, par étapes : chaque étape validée est conservée dans un brouillon.

    L'envoi final est exactement celui d'avant (mêmes formulaires, mêmes champs obligatoires) ; les étapes n'existent que dans la page.
    """
    if request.method == 'POST':
        beer_form = BeerForm(request.POST, request.FILES, prefix='beer', user=request.user)
        drink_form = DrinkForm(request.POST, request.FILES, prefix='drink', user=request.user)
        
        notebooks = posted_notebooks(request)
        if beer_form.is_valid() & drink_form.is_valid():  # & : valide les deux pour afficher toutes les erreurs
            try:
                new_beer = beers.add_beer(request.user, beer_form, drink_form, notebooks)
            except beers.NameTaken:
                beer_form.add_error('name', "Cette bière vient d'être ajoutée par quelqu'un d'autre.")
            else:
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
def save_beer_draft_view(request):
    """Enregistre une étape du brouillon.

    `strict=1` (bouton Suivant) : l'étape est validée par les formulaires de la page, rien n'est conservé si elle est refusée ;
    `strict=0` (retour, fermeture de la page) : on conserve ce qui est là sans rien valider. Réponse JSON, sauf 204 sans contenu en mode souple.
    """
    # Taille annoncée du corps (le corps lui-même n'est plus lisible une fois le formulaire analysé)
    declared = request.META.get('CONTENT_LENGTH', '')
    if not declared.isdecimal() or int(declared) > 20000:
        return JsonResponse({'ok': False, 'errors': ["Envoi trop volumineux."]}, status=413)
    if not BEER_DRAFT_SAVES.hit(request.user.pk):
        return JsonResponse({'ok': False, 'errors': ["Trop d'enregistrements. Réessayez dans quelques minutes."]}, status=429)

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
def discard_beer_draft_view(request):
    """Recommencer : efface le brouillon du membre."""
    BeerDraft.objects.filter(user=request.user).delete()
    return redirect('add_beer')


def add_beer_done_view(request, beer_slug):
    """Page de félicitations après l'ajout d'une bière (réservée à la personne qui vient de l'ajouter)."""
    beer = get_object_or_404(Beer.objects.select_related('brewery'), slug=beer_slug, added_by=request.user, is_deleted=False)
    return render(request, 'add_beer_done.html', {
        'beer': beer,
        'beers_added': Beer.objects.filter(added_by=request.user, is_deleted=False).count(),
    })

def beer_detail_view(request, beer_slug):
    """Affiche les détails d'une bière, ses notes et commentaires. Une bière retirée du catalogue n'est visible que de ses gérants et des
    membres qui l'ont dégustée (pour retrouver leur avis)."""
    beer = get_object_or_404(Beer.objects.select_related('brewery'), slug=beer_slug)
    if not permissions.can_view(request.user, beer):
        raise Http404
    page_views.record(request, page_views.BEER, beer)

    reviews = list(beer_reviews(beer, request.user)[:REVIEWS_PAGE + 1])
    user_drink = with_reaction_counts(Drinks.objects.filter(beer=beer, drinker=request.user)).first()
    user_rating = _rating_summary(user_drink) if user_drink else None
    rating_form = DrinkForm()
    if user_drink:
        rating_form.fields['date'].initial = user_drink.date
        rating_form.fields['note'].initial = user_drink.note
        rating_form.fields['comment'].initial = user_drink.comment

    wishlist_beer_ids = [beer.id] if request.user.wishlist_beers.filter(id=beer.id).exists() else []

    ratings = visible_tastings_of(beer, request.user).aggregate(average=Avg('note'), count=Count('note'))

    context = {
        'beer': beer,
        'drinks': reviews[:REVIEWS_PAGE],
        'reviews_has_more': len(reviews) > REVIEWS_PAGE,
        'average_note': ratings['average'],
        'rating_count': ratings['count'],
        'is_brewery_manager': permissions.is_brewery_manager(request.user, beer),
        'can_edit_beer': permissions.can_edit(request.user, beer),
        'user_rating': user_rating,
        'rating_form': rating_form,
        'wishlist_beer_ids': wishlist_beer_ids,
        **suggestion_menu(CONTENT_TYPES['beer'], beer, request.user),
    }
    return render(request, 'beer_page.html', context)

REVIEWS_PAGE = 10


def _rating_summary(drink):
    """Avis du membre sur la bière, tel que l'affiche sa carte (contexte de dégustation mis en forme)."""
    return {
        'note': drink.note, 'comment': drink.comment, 'photo_url': drink.photo_url, 'date': drink.date, 'slug': drink.slug,
        'likes': drink.likes, 'dislikes': drink.dislikes,
        'notebook_slugs': list(drink.notebooks.values_list('slug', flat=True)),
        'venue_type': drink.venue_type, 'company': drink.company, 'serving_format': drink.serving_format, 'price': drink.price,
        'context': ' · '.join(part for part in (
            drink.get_venue_type_display(), drink.get_company_display(), drink.get_serving_format_display(),
            f"{drink.price:.2f} €".replace('.', ',') if drink.price is not None else '') if part),
    }


def _refusal(user, beer, action):
    """Message de refus si `user` ne peut pas `action` (« modifier », « retirer ») cette bière, sinon None (voir services/catalog/permissions)."""
    if permissions.can_edit(user, beer):
        return None
    if beer.added_by_id == user.pk:
        return f"Cette fiche est vérifiée : seul le gérant de la brasserie peut la {action}."
    return f"Vous n'avez pas l'autorisation de {action} cette bière."


def edit_beer_view(request, beer_slug):
    """Éditer les infos d'une bière qu'on a proposée ou dont on gère la brasserie."""
    
    beer = get_object_or_404(Beer.objects.select_related('brewery'), slug=beer_slug, is_deleted=False)
    refusal = _refusal(request.user, beer, "modifier")
    if refusal:
        messages.error(request, refusal)
        return redirect('beer_detail', beer_slug=beer.slug)
    if request.method == 'POST':
        form = BeerForm(request.POST, request.FILES, instance=beer, user=request.user)
        if form.is_valid():
            beers.update_beer(form, request.user)
            messages.success(request, "Les informations de la bière ont été mises à jour.")
            return redirect('beer_detail', beer_slug=beer.slug)
    else:
        form = BeerForm(instance=beer, user=request.user)
    return render(request, 'edit_beer.html', {'form': form, 'beer': beer})

def delete_beer_view(request, beer_slug):
    """Soft-delete d'une bière du catalogue."""
    
    beer = get_object_or_404(Beer.objects.select_related('brewery'), slug=beer_slug, is_deleted=False)
    refusal = _refusal(request.user, beer, "retirer")
    if refusal:
        messages.error(request, refusal)
        return redirect('beer_detail', beer_slug=beer.slug)
    if request.method == 'POST':
        beers.retire_beer(beer, request.user)
        messages.success(request, "Bière retirée du catalogue. Vos notes personnelles sont conservées.")
        return redirect('index')
    return redirect('beer_detail', beer_slug=beer.slug)
