"""Modèles de l'application, un module par domaine ; tout est ré-exporté ici : `from app.models import Beer` continue de fonctionner."""
from .mixins import GeocodableMixin, MatchKeyMixin, PostalAddressMixin, VerifiableMixin, OfficialImageMixin
from .users import STAFF_GROUP, BeerUserManager, BeerUser, UserFollow, UserBlock
from .establishments import Brewery, Bar
from .beers import Beer, BeerDraft, Drinks, DrinkReaction, CustomNotebook
from .places import BeerSpot, PostalCode, ReverseGeocode
from .analytics import AnalyticsLayout, AnalyticsView, AnalyticsTile
from .feedback import Feedback, FeedbackMessage
from .reports import Report
from .moderation import ModerationEntryQuerySet, ModerationEntry
from .notifications import Notification, UserAchievementState
from .claims import EstablishmentClaim, ManagerInvitation
from .campaigns import EmailCampaign, CampaignRecipient
from .system import PolicyNotice, ThrottleHit, AccountDeletion, QuotaUsage
from . import signals  # noqa: F401  (branche les réactions automatiques)
