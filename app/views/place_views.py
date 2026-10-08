"""Logique commune aux établissements (brasseries et bars) : édition et gestion de l'équipe."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import ClaimForm
from ..models import BeerUser, EstablishmentClaim
from ..services import claims
from ..services.notifications import notify
from ..services.places import BAR, BREWERY, PlaceKind, kind_of  # noqa: F401  (réexportés pour les vues bar/brasserie)


def is_manager(place, user):
    return place.managers.filter(id=user.id).exists()


def edit_place(request, kind, slug):
    """Permet aux managers de modifier les informations de l'établissement."""
    place = kind.get(slug)

    if not is_manager(place, request.user):
        messages.error(request, "Vous n'avez pas l'autorisation de modifier cet établissement.")
        return kind.redirect_to_detail(place)

    if request.method == 'POST':
        form = kind.edit_form(request.POST, request.FILES, instance=place)
        if form.is_valid():
            form.save()

            notify('place_updated', place.managers.exclude(id=request.user.id), sender=request.user, **{kind.key: place})

            messages.success(request, f"Les informations de {kind.noun} ont été mises à jour.")
            return kind.redirect_to_detail(place)
    else:
        form = kind.edit_form(instance=place)

    return render(request, 'edit_place.html', {'form': form, 'place': place, 'place_type': kind.key})


def add_manager(request, kind, slug):
    """Ajoute un utilisateur comme collaborateur."""
    place = kind.get(slug)

    if request.method == 'POST' and is_manager(place, request.user):
        user_to_add = get_object_or_404(BeerUser, username=request.POST.get('username'), is_active=True)
        place.managers.add(user_to_add)

        notify('manager_added', [user_to_add], sender=request.user, **{kind.key: place})

        messages.success(request, f"{user_to_add.username} a été ajouté aux collaborateurs.")

    return kind.redirect_to_detail(place)


def remove_manager(request, kind, slug, username):
    """Retire l'accès à un collaborateur (sauf soi-même)."""
    place = kind.get(slug)

    if request.method == 'POST' and is_manager(place, request.user):
        if request.user.username != username:  # Empêcher de se supprimer soi-même
            user_to_remove = get_object_or_404(BeerUser, username=username)
            place.managers.remove(user_to_remove)

            notify('manager_removed', [user_to_remove], sender=request.user, text_content=place.name)

            messages.success(request, f"L'accès de {user_to_remove.username} a été retiré.")

    return kind.redirect_to_detail(place)


def search_users_for_manager(request, kind, slug):
    """Recherche AJAX de collaborateurs, limitée à 10 résultats pour les performances."""
    query = request.GET.get('q', '').strip()
    place = kind.get(slug)

    # Sécurité : Seul un manager peut chercher des collaborateurs
    if not is_manager(place, request.user):
        return JsonResponse({'error': 'Non autorisé'}, status=403)

    if len(query) < 2:
        return JsonResponse({'users': []})

    # On exclut ceux qui sont DÉJÀ managers
    existing_managers = place.managers.values_list('id', flat=True)
    users = (
        BeerUser.objects.filter(username__icontains=query, is_active=True)
        .exclude(id__in=existing_managers).prefetch_related('socialaccount_set')[:10]
    )
    return JsonResponse({'users': [{'username': u.username, 'avatar_url': u.avatar_url} for u in users]})


@login_required(login_url='login')
@require_POST
def cancel_claim(request, claim_id):
    """Le demandeur retire sa demande en attente."""
    claim = get_object_or_404(EstablishmentClaim, pk=claim_id, claimant=request.user)
    try:
        claims.cancel(claim, request.user)
        messages.success(request, "Votre demande a été retirée.")
    except claims.ClaimError as error:
        messages.error(request, str(error))
    return redirect('account')


def place_context(place, user):
    """Contexte commun aux pages de détail : droits de l'utilisateur, équipe visible des managers, demande de gestion possible ou en cours."""
    manager = is_manager(place, user)
    kind = kind_of(place)
    pending = None if manager else claims.pending_claim(user, kind, place)
    return {
        'is_manager': manager,
        'current_managers': place.managers.all() if manager else [],
        'can_claim': not manager and pending is None and user.is_active,
        'pending_claim': pending,
    }


def claim_place(request, kind, slug):
    """Demande de gestion d'une fiche existante par un membre connecté : SIRET contrôlé, puis examen par l'équipe."""
    place = kind.get(slug)
    if is_manager(place, request.user):
        messages.info(request, "Vous gérez déjà cette fiche.")
        return kind.redirect_to_detail(place)
    form = ClaimForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            claims.open_claim(request.user, kind, place, form.cleaned_data['siret'], form.cleaned_data['message'])
        except claims.ClaimError as error:
            form.add_error(error.field if error.field in form.fields else None, str(error))
        else:
            messages.success(request, "Demande envoyée. L'équipe vérifie le SIRET puis vous répond par notification et par e-mail.")
            return kind.redirect_to_detail(place)
    return render(request, 'claim_place.html', {'form': form, 'place': place, 'place_type': kind.key, 'back_url': kind.detail_path(place)})
