"""Logique commune aux établissements (brasseries et bars) : édition et gestion de l'équipe."""
from dataclasses import dataclass

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import BarEditForm, BreweryEditForm
from ..models import Bar, BeerUser, Brewery
from ..services.notifications import notify


@dataclass(frozen=True)
class PlaceKind:
    """Ce qui diffère entre une brasserie et un bar ; tout le reste est partagé."""
    key: str  # 'brewery' | 'bar' : nom du champ FK de Notification et préfixe des URLs
    model: type
    edit_form: type
    noun: str  # « la brasserie » / « le bar »

    @property
    def detail_url(self):
        return f'{self.key}_detail'

    def detail_kwargs(self, place):
        return {f'{self.key}_slug': place.slug}

    def redirect_to_detail(self, place):
        return redirect(self.detail_url, **self.detail_kwargs(place))

    def get(self, slug):
        return get_object_or_404(self.model, slug=slug)


BREWERY = PlaceKind('brewery', Brewery, BreweryEditForm, 'la brasserie')
BAR = PlaceKind('bar', Bar, BarEditForm, 'le bar')


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


def place_context(place, user):
    """Contexte commun aux pages de détail : droits de l'utilisateur et équipe visible des managers."""
    manager = is_manager(place, user)
    return {
        'is_manager': manager,
        'current_managers': place.managers.all() if manager else [],
    }
