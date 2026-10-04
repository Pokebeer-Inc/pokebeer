from functools import wraps

from django.http import HttpResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from ..models import BeerUser, UserBlock
from ..services.throttle import client_ip
from ..services.achievements import (  # noqa: F401  (ré-exportés : les vues importent depuis ici)
    TIER_NAMES, TIER_SLUGS, TIER_XP_REWARDS, check_and_notify_achievements, get_user_achievements,
)

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

def get_blocked_users(user):
    """Retourne la liste des IDs d'utilisateurs avec qui il y a un blocage."""
    if not user.is_authenticated: return []
    blocked_by_me = UserBlock.objects.filter(blocker=user).values_list('blocked_id', flat=True)
    blocking_me = UserBlock.objects.filter(blocked=user).values_list('blocker_id', flat=True)
    return list(set(blocked_by_me) | set(blocking_me))

def get_excluded_users(user):
    """Retourne la liste des IDs d'utilisateurs à masquer : blocages et comptes suspendus."""
    suspended = BeerUser.objects.filter(is_active=False).values_list('id', flat=True)
    return list(set(get_blocked_users(user)) | set(suspended))


def limit_posts(rule):
    """Décorateur de vue : chaque envoi de formulaire (POST) compte pour la limite par IP ; au-delà, refus 429."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method == 'POST':
                ip = client_ip(request)
                if rule.exceeded(ip):
                    return HttpResponse("Trop de tentatives. Réessayez dans quelques minutes.", status=429, content_type='text/plain; charset=utf-8')
                rule.record(ip)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def previous_page(request, default='index'):
    """Page d'où vient le visiteur, uniquement si elle est sur ce site : le Referer est fourni par le client."""
    referer = request.META.get('HTTP_REFERER')
    if url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return referer
    return reverse(default)
