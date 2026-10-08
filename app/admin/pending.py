"""Éléments « à traiter » : pastille du menu latéral et KPI en tête de liste, pour les modèles à statut."""
from ..models import Feedback, Report
from ..services import claims

PENDING_REPORTS_EXCLUDED_STATUS = 'resolved'


def pending_feedback_count(request=None):
    return Feedback.objects.filter(status='pending').count()


def pending_claims_count(request=None):
    """Demandes de gestion d'établissement qui attendent une décision."""
    return claims.pending_count()


def pending_report_count(request=None):
    """Signalements envoyés ou en cours d'examen (hors traités)."""
    return Report.objects.exclude(status=PENDING_REPORTS_EXCLUDED_STATUS).count()


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
