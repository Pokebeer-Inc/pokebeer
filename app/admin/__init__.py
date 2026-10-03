"""Administration (django-unfold), un module par domaine ; les imports enregistrent les ModelAdmin."""
from . import catalog, feedback, moderation, reports, users  # noqa: F401
from .dashboard import dashboard_callback  # noqa: F401
