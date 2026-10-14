from dataclasses import dataclass
from functools import wraps

from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from ..forms import DrinkForm
from ..services.catalog.selectors import member_marks, pickable_drinks
from ..services.protection.throttle import client_ip

MAX_OFFSET = 100_000

def posted_notebooks(request):
    """Carnets de l'utilisateur désignés par les slugs du formulaire ; les slugs inconnus ou d'autrui sont ignorés."""
    return list(request.user.custom_notebooks.filter(slug__in=request.POST.getlist('notebooks')))

def parse_offset(request):
    """Lit le paramètre ?offset= d'un chargement paginé. Renvoie None s'il n'est pas un entier entre 0 et MAX_OFFSET."""
    raw = request.GET.get('offset', '0').strip()
    if not raw.isdecimal() or not raw.isascii() or int(raw) > MAX_OFFSET:
        return None
    return int(raw)

TOO_MANY_ATTEMPTS = "Trop de tentatives. Réessayez dans quelques minutes."
TOO_MANY_SEARCHES = "Trop de recherches, réessayez dans un moment."


def by_ip(request):
    return client_ip(request)


def by_user(request):
    return request.user.pk


def throttle(rule, key=by_ip, methods=None, json=False, message=TOO_MANY_ATTEMPTS):
    """Décorateur de vue : chaque requête (des méthodes `methods`, toutes par défaut) consomme une tentative de `rule` pour la clé
    `key(request)`, de façon atomique ; au-delà, refus 429 (JSON `{"error": message}` pour une API, texte sinon).

    La clé `by_user` suppose un membre connecté : c'est le cas de toute vue non marquée `login_not_required` (LoginRequiredMiddleware)."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if (methods is None or request.method in methods) and not rule.hit(key(request)):
                if json:
                    return JsonResponse({'error': message}, status=429)
                return HttpResponse(message, status=429, content_type='text/plain; charset=utf-8')
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def limit_posts(rule):
    """Chaque envoi de formulaire (POST) compte pour la limite par IP ; au-delà, refus 429."""
    return throttle(rule, methods=('POST',))


def beer_list_context(user, beers):
    """Contexte d'une liste de bières à noter : les bières, celles déjà notées ou à goûter par le membre, et le formulaire de notation."""
    rated, wished = member_marks(user, [beer.id for beer in beers])
    return {'beers': beers, 'rating_form': DrinkForm(), 'rated_beer_ids': rated, 'wishlist_beer_ids': wished}


@dataclass(frozen=True)
class PickerMode:
    """Sélecteur de dégustations : type de case, nom du champ envoyé, valeur (slug de la dégustation ou de la bière)."""
    input_type: str
    name: str
    value: str
    catalog_only: bool = False

    @property
    def row_context(self):
        return {'input_type': self.input_type, 'name': self.name, 'value': self.value}


PICKER_MODES = {
    'drinks': PickerMode('checkbox', 'drinks', 'drink'),            # carnets, lieux de la carte : une case par dégustation
    'top': PickerMode('radio', 'beer_slug', 'beer', catalog_only=True),  # Top 3 : une bière dégustée, encore au catalogue
}
PICKER_PAGE = 10  # = taille d'une page de « Charger plus »


def picker_context(user, mode_key):
    """Contexte de partials/drink_picker.html : premières lignes, total et adresse de la suite (chargeur `pick_drinks`)."""
    mode = PICKER_MODES[mode_key]
    drinks = pickable_drinks(user, catalog_only=mode.catalog_only)
    first = list(drinks[:PICKER_PAGE + 1])
    return {
        **mode.row_context, 'drinks': first[:PICKER_PAGE], 'has_more': len(first) > PICKER_PAGE,
        'total': drinks.count() if len(first) > PICKER_PAGE else len(first),
        'url': f"{reverse('load_more_generic', args=['pick_drinks'])}?mode={mode_key}",
    }


def chosen_tab(value, tabs, aliases=None, default=None):
    """Onglet demandé s'il fait partie de `tabs` (les anciens noms, français, passent par `aliases` : adresses déjà enregistrées ou
    envoyées), sinon `default`. Le paramètre n'est jamais cru tel quel."""
    value = (aliases or {}).get(value, value)
    return value if value in tabs else default


def previous_page(request, default='index'):
    """Page d'où vient le visiteur, uniquement si elle est sur ce site : le Referer est fourni par le client."""
    referer = request.META.get('HTTP_REFERER')
    if url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return referer
    return reverse(default)
