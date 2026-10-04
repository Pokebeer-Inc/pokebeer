"""Suivi de l'activité des membres (base de la suppression des comptes inactifs)."""
from .services import inactivity


class ActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated:
            inactivity.record_activity(user)
        return self.get_response(request)
