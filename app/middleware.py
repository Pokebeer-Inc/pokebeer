"""Suivi de l'activité des membres (base de la suppression des comptes inactifs)."""
from django.conf import settings

from .services import csp, inactivity


class ActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated:
            inactivity.record_activity(user)
        return self.get_response(request)


class SecurityHeadersMiddleware:
    """Ajoute la CSP et la Permissions-Policy à chaque réponse (sans écraser un en-tête déjà posé par une vue)."""

    PERMISSIONS_POLICY = 'geolocation=(self), camera=(self), microphone=(), payment=(), usb=()'

    def __init__(self, get_response):
        self.get_response = get_response
        self.admin_prefix = f'/{settings.ADMIN_URL}'

    def __call__(self, request):
        response = self.get_response(request)
        policy = csp.build_policy(settings.SUPABASE_URL, admin=request.path.startswith(self.admin_prefix))
        response.headers.setdefault('Content-Security-Policy', policy)
        response.headers.setdefault('Permissions-Policy', self.PERMISSIONS_POLICY)
        return response
