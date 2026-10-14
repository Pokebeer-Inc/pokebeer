from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.utils.decorators import method_decorator
from django.views.generic import RedirectView

__all__ = ['PrivacyPolicyView']


@method_decorator(login_not_required, name='dispatch')
class PrivacyPolicyView(RedirectView):
    """Adresse stable de la politique de confidentialité sur le site : renvoie vers le document en vigueur (réglage, jamais une saisie)."""
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return settings.PRIVACY_POLICY_URL
