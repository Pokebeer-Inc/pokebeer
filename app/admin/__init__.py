"""Administration (django-unfold), un module par domaine ; les imports enregistrent les ModelAdmin."""
from django.contrib import admin

from ..auth_forms import ThrottledAdminAuthenticationForm
from . import blocks, catalog, feedback, moderation, policy, reports, users  # noqa: F401
from .dashboard import dashboard_callback  # noqa: F401


admin.site.login_form = ThrottledAdminAuthenticationForm
