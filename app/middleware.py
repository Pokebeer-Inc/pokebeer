"""Suivi de l'activité des membres (base de la suppression des comptes inactifs)."""
import secrets

from django.conf import settings
from django.contrib.auth import middleware as auth_middleware
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from .services.protection import csp
from .services.members import inactivity


class LoginRequiredMiddleware(auth_middleware.LoginRequiredMiddleware):
    """Toute page exige d'être connecté, sauf celles marquées `@login_not_required` (connexion, inscription, mot de passe oublié, liens des
    e-mails, fichiers publics…) : une nouvelle vue est protégée par défaut, un oubli ne peut plus l'exposer.

    L'administration garde son propre contrôle (sa page de connexion et les droits staff) : ses adresses ne passent pas par ici."""

    def __init__(self, get_response):
        super().__init__(get_response)
        self.admin_prefix = f'/{settings.ADMIN_URL}'

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.path.startswith(self.admin_prefix):
            return None
        return super().process_view(request, view_func, view_args, view_kwargs)


class ActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and inactivity.record_activity(user):
            # Session glissante : prolongée à chaque visite enregistrée (au plus toutes les 12 h, pas à chaque requête)
            request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        return self.get_response(request)


class SecurityHeadersMiddleware:
    """Ajoute la CSP et la Permissions-Policy à chaque réponse (sans écraser un en-tête déjà posé par une vue)."""

    PERMISSIONS_POLICY = 'geolocation=(self), camera=(self), microphone=(), payment=(), usb=()'

    def __init__(self, get_response):
        self.get_response = get_response
        self.admin_prefix = f'/{settings.ADMIN_URL}'

    def __call__(self, request):
        # Jeton propre à cette réponse : les gabarits le lisent (`request.csp_nonce`) pour leurs rares scripts en ligne
        request.csp_nonce = secrets.token_urlsafe(16)
        response = self.get_response(request)
        policy = csp.build_policy(settings.SUPABASE_URL, admin=request.path.startswith(self.admin_prefix), nonce=request.csp_nonce)
        response.headers.setdefault('Content-Security-Policy', policy)
        response.headers.setdefault('Permissions-Policy', self.PERMISSIONS_POLICY)
        return response


class OnboardingMiddleware:
    """Tant qu'un membre n'a pas passé les pages qui suivent l'inscription (date de naissance puis genre), rien d'autre n'est accessible.

    Les navigations sont renvoyées vers ces pages (la page demandée est mémorisée pour y revenir ensuite) ; tout le reste (envois, appels
    d'API) est refusé. Fonctionne pour toutes les voies d'inscription, Google compris.
    """
    ALLOWED_PREFIXES = ('/welcome/', '/logout/', '/privacy-policy/', '/accounts/', '/static/', '/media/', '/favicon', '/.well-known/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and not user.onboarding_done and not request.path.startswith(self.ALLOWED_PREFIXES):
            accept = request.headers.get('Accept', 'text/html')
            if request.method in ('GET', 'HEAD') and 'text/html' in accept:
                # On ne retient que la page qu'un membre a vraiment ouverte (le navigateur le dit par Sec-Fetch-Dest) : pas les requêtes
                # automatiques (outils de développement, icônes, vérifications) qui n'ont rien à faire comme destination
                if request.headers.get('Sec-Fetch-Dest') == 'document':
                    request.session['onboarding_next'] = request.get_full_path()
                return redirect('onboarding')
            return HttpResponseForbidden("Terminez votre inscription pour continuer.", content_type='text/plain; charset=utf-8')
        return self.get_response(request)
