"""Jours d'activité des membres : une ligne (membre, jour) la première fois qu'un membre connecté est vu dans la journée.

Le jour déjà enregistré est retenu dans la session : une visite ordinaire ne coûte aucune requête, seule la première de la journée écrit.
"""
from django.utils import timezone

from ...models import ActivityDay
from . import safely

SESSION_KEY = 'activity_day'


@safely
def _write(user, today):
    # Deux appareils ou deux sessions le même jour : la contrainte d'unicité absorbe le doublon
    ActivityDay.objects.bulk_create([ActivityDay(user=user, day=today)], ignore_conflicts=True)
    return True


def record_today(request):
    user = request.user
    if not user.is_authenticated:
        return
    today = timezone.localdate()
    if request.session.get(SESSION_KEY) != today.isoformat() and _write(user, today):
        request.session[SESSION_KEY] = today.isoformat()
