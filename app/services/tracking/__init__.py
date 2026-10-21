"""Mesures d'usage minimales (modèles dans models/tracking.py) : vues des fiches, jours d'activité, demandes sans résultat.

Règles communes :
- une mesure ne doit jamais faire échouer la page qui la déclenche (`safely`) ;
- on stocke des compteurs, jamais « qui a fait quoi » ;
- chaque mesure a sa durée de conservation et sa purge (`retention.purge_expired`, appelée par la tâche quotidienne).
"""
import logging
from functools import wraps

from django.db import transaction

logger = logging.getLogger(__name__)


def safely(function):
    """Une mesure en échec est journalisée et ignorée ; sa transaction est isolée pour ne pas invalider celle de la requête."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            with transaction.atomic():
                return function(*args, **kwargs)
        except Exception:
            logger.exception("Mesure d'usage impossible (%s)", function.__name__)
            return None
    return wrapper
