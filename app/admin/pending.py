"""Éléments « à traiter » : pastille du menu latéral et KPI en tête de liste, pour les modèles à statut."""
from ..models import Beer, Feedback, Report, Style
from ..services.establishments import claims

PENDING_REPORTS_EXCLUDED_STATUS = 'resolved'


def pending_feedback_count(request=None):
    return Feedback.objects.filter(status='pending').count()


def pending_claims_count(request=None):
    """Demandes de gestion d'établissement qui attendent une décision."""
    return claims.pending_count()


def pending_report_count(request=None):
    """Signalements envoyés ou en cours d'examen (hors traités)."""
    return Report.objects.exclude(status=PENDING_REPORTS_EXCLUDED_STATUS).count()


def pending_unbranded_beer_count(request=None):
    """Bières ajoutées sans brasserie, que le staff doit rattacher (ou créer la brasserie) : la file « Bières à compléter »."""
    return Beer.objects.unbranded().count()


def pending_unofficial_style_count(request=None):
    """Styles saisis par des membres, absents du référentiel, que le staff doit ranger dans une famille ou fusionner avec un style officiel."""
    return Style.objects.filter(is_official=False).count()


class PendingKpiMixin:
    """Affiche en tête de la liste le nombre d'éléments en attente de traitement."""

    list_before_template = "admin/pending_kpi.html"
    pending_label = "à traiter"
    pending_counter = staticmethod(lambda request: 0)  # renvoie le nombre d'éléments en attente

    def changelist_view(self, request, extra_context=None):
        extra_context = {
            **(extra_context or {}),
            "pending_count": self.pending_counter(request),
            "pending_label": self.pending_label,
        }
        return super().changelist_view(request, extra_context)
