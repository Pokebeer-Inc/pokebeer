"""Choix des e-mails promotionnels sans connexion (lien signé reçu par e-mail) et fichier de vérification des App Links Android."""
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ..services import app_links, marketing
from ..services.throttle import EMAIL_PREFERENCES_BY_IP
from .utils import limit_posts

__all__ = ['email_preferences', 'email_unsubscribe', 'assetlinks']

CHOICES = {'accept': True, 'refuse': False}


def _member_or_404(token):
    """Un jeton falsifié et un compte supprimé donnent la même réponse : rien ne permet de sonder les comptes."""
    user = marketing.user_for_token(token)
    if user is None:
        raise Http404
    return user


@never_cache
@limit_posts(EMAIL_PREFERENCES_BY_IP)
@require_http_methods(['GET', 'POST'])
def email_preferences(request, token):
    """Page de désinscription ou de retour aux e-mails promotionnels : deux boutons, protégés par le jeton signé et par CSRF."""
    user = _member_or_404(token)
    saved = None
    if request.method == 'POST':
        choice = CHOICES.get(request.POST.get('choice'))
        if choice is None:
            return HttpResponse(status=400)
        marketing.set_consent(user, choice, marketing.EMAIL_LINK)
        saved = choice
    response = render(request, 'email_preferences.html', {'member': user, 'token': token, 'saved': saved})
    response['Referrer-Policy'] = 'no-referrer'  # le jeton est dans l'adresse
    return response


@csrf_exempt  # appelé par le client de messagerie (RFC 8058), sans cookie : le jeton signé tient lieu d'authentification
@require_POST
def email_unsubscribe(request, token):
    """Désinscription en un clic depuis Gmail, Apple Mail… : ne sait que refuser, jamais accepter."""
    marketing.set_consent(_member_or_404(token), False, marketing.EMAIL_LINK)
    return HttpResponse(status=200)


@require_GET
@cache_control(public=True, max_age=3600)
def assetlinks(request):
    """Lie le domaine à l'application Android : ses liens s'y ouvrent directement quand elle est installée."""
    return JsonResponse(app_links.assetlinks(), safe=False)
