from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from ..models import Beer, Drinks
from ..services.catalog.recommendations import get_recommended_beers
from ..services.catalog.selectors import get_activity, activity_kind, ACTIVITY_TITLES
from .search_views import build_results, normalize_tab

HOME_RECOMMENDATIONS = 10
HOME_ACTIVITY = 10


def unrated_beers_for(user):
    """Bières du catalogue que le membre n'a pas encore notées (sous-requête : rien n'est chargé en mémoire)."""
    return (Beer.objects.filter(is_deleted=False)
            .exclude(id__in=Drinks.objects.filter(drinker=user).values('beer'))
            .select_related('brewery', 'added_by'))


@ensure_csrf_cookie
def index(request):
    """Recherche = accueil : sans saisie, recommandations et fil d'activité ; avec `q` ou un onglet, les résultats."""
    user = request.user
    # Sans paramètre (ou avec l'onglet « Tout » seul) on affiche l'accueil, sinon les résultats de recherche
    searching = bool(request.GET.get('q') or request.GET.get('uq') or normalize_tab(request.GET.get('tab')) not in (None, '', 'all'))

    recommended = get_recommended_beers(Drinks.objects.filter(drinker=user), unrated_beers_for(user), HOME_RECOMMENDATIONS)
    activity = get_activity(user, HOME_ACTIVITY)
    kind = activity_kind(activity)
    context = {
        'greeting': 'Bonjour' if timezone.localtime().hour < 18 else 'Bonsoir',  # le navigateur l'ajuste à l'heure de l'appareil
        'searching': searching,
        'recommended_beers': list(recommended),
        'activity': activity,
        'activity_kind': kind,
        'activity_title': ACTIVITY_TITLES[kind],
    }
    context.update(build_results(request, default_tab='all'))
    return render(request, 'home.html', context)
