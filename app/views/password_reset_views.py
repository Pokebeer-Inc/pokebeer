"""Réinitialisation du mot de passe : demande, lien reçu par e-mail, confirmation."""
from django.conf import settings
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import FormView, TemplateView

from ..forms import NewPasswordForm, PasswordResetRequestForm
from ..services import password_reset
from ..services.throttle import PASSWORD_RESET_BY_IP, PASSWORD_RESET_CONFIRM_BY_IP
from ..services.timing import minimum_duration
from .utils import limit_posts

__all__ = ['PasswordResetRequestView', 'PasswordResetDoneView', 'PasswordResetConfirmView', 'PasswordResetCompleteView']


@method_decorator(limit_posts(PASSWORD_RESET_BY_IP), name='dispatch')
class PasswordResetRequestView(FormView):
    template_name = 'password_reset/request.html'
    form_class = PasswordResetRequestForm
    success_url = reverse_lazy('password_reset_done')

    def form_valid(self, form):
        # Même réponse, au même rythme, que l'adresse ait un compte ou non
        with minimum_duration(settings.PASSWORD_RESET_MIN_SECONDS):
            password_reset.request_password_reset(form.cleaned_data['email'])
        return super().form_valid(form)


class PasswordResetDoneView(TemplateView):
    template_name = 'password_reset/done.html'


@method_decorator(limit_posts(PASSWORD_RESET_CONFIRM_BY_IP), name='dispatch')
class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """Le jeton de l'URL est déplacé en session par Django avant l'affichage du formulaire (il ne fuit pas via le Referer)."""
    template_name = 'password_reset/confirm.html'
    form_class = NewPasswordForm
    success_url = reverse_lazy('password_reset_complete')

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        # Un lien ne sert qu'à un compte actif qui a un mot de passe (jamais un compte Google ou suspendu)
        return user if user is not None and password_reset.can_reset(user) else None

    def form_valid(self, form):
        response = super().form_valid(form)
        password_reset.notify_password_changed(self.user)
        return response


class PasswordResetCompleteView(TemplateView):
    template_name = 'password_reset/complete.html'
