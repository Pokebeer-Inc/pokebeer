"""Pages des établissements (brasseries et bars) : une seule définition pour les deux types (fiche, édition, revendication, équipe).

Les vues propres à un type sont produites par `views_for(kind)` ; seules les fiches diffèrent (une brasserie liste ses bières).
"""
from types import SimpleNamespace

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from ..forms import ClaimForm
from ..models import EstablishmentClaim, ManagerInvitation
from ..services.catalog.selectors import brewery_beers
from ..services.establishments import claims, team
from ..services.establishments.team import is_manager
from ..services.moderation.content import CONTENT_TYPES
from ..services.moderation.suggestions import menu_context as suggestion_menu
from ..services.establishments.places import BAR, BREWERY, PlaceKind, kind_of  # noqa: F401  (réexportés pour les vues bar/brasserie)
from ..services.protection.throttle import AUTOCOMPLETE_BY_USER
from .utils import TOO_MANY_SEARCHES, beer_list_context, by_user, throttle

BREWERY_BEERS_PAGE = 10


def edit_place(request, kind, slug):
    """Permet aux managers de modifier les informations de l'établissement."""
    place = kind.get(slug)

    if not is_manager(request.user, place):
        messages.error(request, "Vous n'avez pas l'autorisation de modifier cet établissement.")
        return kind.redirect_to_detail(place)

    if request.method == 'POST':
        form = kind.edit_form(request.POST, request.FILES, instance=place)
        if form.is_valid():
            team.update_place(form, request.user)
            messages.success(request, f"Les informations de {kind.noun} ont été mises à jour.")
            return kind.redirect_to_detail(place)
    else:
        form = kind.edit_form(instance=place)

    return render(request, 'edit_place.html', {'form': form, 'place': place, 'place_type': kind.key})


def add_manager(request, kind, slug):
    """Invite un membre dans l'équipe : il ne devient gérant (et n'obtient le rôle) qu'en acceptant."""
    place = kind.get(slug)
    if request.method == 'POST':
        try:
            invitation = team.invite(place, request.user, request.POST.get('username'))
        except team.TeamError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"Invitation envoyée à {invitation.invitee.username}. L'accès sera accordé à son acceptation.")
    return kind.redirect_to_detail(place)


def remove_manager(request, kind, slug, username):
    """Retire l'accès à un collaborateur (sauf soi-même)."""
    place = kind.get(slug)
    if request.method == 'POST':
        try:
            removed = team.remove_manager(place, request.user, username)
        except team.TeamError as error:
            messages.error(request, str(error))
        else:
            if removed:
                messages.success(request, f"L'accès de {removed.username} a été retiré.")
    return kind.redirect_to_detail(place)


@require_GET
@throttle(AUTOCOMPLETE_BY_USER, key=by_user, json=True, message=TOO_MANY_SEARCHES)
def search_users_for_manager(request, kind, slug):
    """Recherche AJAX des membres à inviter (10 résultats au plus) ; réservée aux gérants."""
    query = request.GET.get('q', '').strip()
    place = kind.get(slug)
    if not is_manager(request.user, place):
        return JsonResponse({'error': 'Non autorisé'}, status=403)
    if len(query) < 2:
        return JsonResponse({'users': []})
    users = team.search_invitable(place, request.user, query)
    return JsonResponse({'users': [{'username': u.username, 'avatar_url': u.avatar_url} for u in users]})


@require_POST
def cancel_invitation(request, invitation_slug):
    """Un gérant retire une invitation en attente de son établissement."""
    invitation = get_object_or_404(ManagerInvitation.objects.select_related('brewery', 'bar', 'invitee'), slug=invitation_slug)
    place = invitation.place
    try:
        team.cancel(invitation, request.user)
    except team.TeamError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Invitation de {invitation.invitee.username} retirée.")
    return kind_of(place).redirect_to_detail(place)


INVITATION_ANSWERS = {'accept': True, 'decline': False}


@require_POST
def respond_invitation(request, invitation_slug):
    """Le membre invité accepte ou refuse de rejoindre l'équipe."""
    accept = INVITATION_ANSWERS.get(request.POST.get('answer'))
    if accept is None:
        messages.error(request, "Réponse invalide.")
        return redirect('account')
    try:
        invitation = team.respond(invitation_slug, request.user, accept)
    except team.TeamError as error:
        messages.error(request, str(error))
        return redirect('account')
    place = invitation.place
    if accept:
        messages.success(request, f"Vous faites désormais partie de l'équipe de {place.name}.")
        return kind_of(place).redirect_to_detail(place)
    messages.info(request, f"Invitation de {place.name} refusée.")
    return redirect('account')


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
    """Contexte commun aux pages de détail : droits de l'utilisateur, équipe et invitations visibles des managers, demande de gestion
    possible ou en cours."""
    manager = is_manager(user, place)
    kind = kind_of(place)
    pending = None if manager else claims.pending_claim(user, kind, place)
    return {
        'is_manager': manager,
        'current_managers': place.managers.all() if manager else [],
        'pending_invitations': list(team.invitations_of(place)) if manager else [],
        'can_claim': not manager and pending is None and user.is_active,
        'pending_claim': pending,
        **suggestion_menu(CONTENT_TYPES[kind.key], place, user),
    }


def claim_place(request, kind, slug):
    """Demande de gestion d'une fiche existante par un membre connecté : SIRET contrôlé, puis examen par l'équipe."""
    place = kind.get(slug)
    if is_manager(request.user, place):
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


def brewery_detail(request, brewery_slug):
    """Fiche d'une brasserie et ses bières (les premières ; la suite par « Charger plus »)."""
    brewery = BREWERY.get(brewery_slug)
    all_beers = brewery_beers(brewery)
    beers = list(all_beers[:BREWERY_BEERS_PAGE + 1])
    return render(request, 'brewery_page.html', {
        'brewery': brewery,
        **beer_list_context(request.user, beers[:BREWERY_BEERS_PAGE]),
        'beers_has_more': len(beers) > BREWERY_BEERS_PAGE,
        'beer_count': all_beers.count() if len(beers) > BREWERY_BEERS_PAGE else len(beers),
        **place_context(brewery, request.user),
    })


def bar_detail(request, bar_slug):
    bar = BAR.get(bar_slug)
    return render(request, 'bar_page.html', {'bar': bar, **place_context(bar, request.user)})


def views_for(kind, detail):
    """Vues d'un type d'établissement ; le slug arrive dans le paramètre d'URL `<type>_slug`."""
    slug = f'{kind.key}_slug'
    return SimpleNamespace(
        detail=detail,
        edit=lambda request, **kwargs: edit_place(request, kind, kwargs[slug]),
        claim=lambda request, **kwargs: claim_place(request, kind, kwargs[slug]),
        add_manager=lambda request, **kwargs: add_manager(request, kind, kwargs[slug]),
        remove_manager=lambda request, username, **kwargs: remove_manager(request, kind, kwargs[slug], username),
        search_users=lambda request, **kwargs: search_users_for_manager(request, kind, kwargs[slug]),
    )


BREWERY_VIEWS = views_for(BREWERY, brewery_detail)
BAR_VIEWS = views_for(BAR, bar_detail)
