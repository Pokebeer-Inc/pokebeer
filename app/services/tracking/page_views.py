"""Vues des fiches (bière, brasserie, bar) : nombre de vues et de visiteurs distincts par fiche et par jour.

Vie privée : la ligne publique (PageView) ne contient que des compteurs. Pour ne compter un visiteur qu'une fois par jour, on garde une
empreinte HMAC (clé du site) de « jour, fiche, membre » : elle ne permet pas de retrouver le membre sans la clé, ne relie pas deux fiches
entre elles (la fiche fait partie de l'empreinte) et est supprimée le lendemain (retention.py).
Ne sont comptées ni les visites de l'équipe, ni celles des gérants de la fiche : leurs consultations de contrôle fausseraient la mesure.
"""
import hashlib
import hmac

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from ...models import PageView, PageViewVisitor
from . import safely
from .counters import increment

BEER, BREWERY, BAR = PageView.Kind.BEER, PageView.Kind.BREWERY, PageView.Kind.BAR


def _digest(day, kind, object_id, user_id):
    message = f'{day.isoformat()}|{kind}|{object_id}|{user_id}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def _is_manager(user, kind, obj):
    """Gérant de la fiche (pour une bière : de sa brasserie). Les groupes du membre sont déjà en mémoire : un membre ordinaire ne coûte aucune requête."""
    if not (user.is_brewer or user.is_bartender):
        return False
    place = obj.brewery if kind == BEER else obj
    return bool(place) and place.managers.filter(pk=user.pk).exists()


def _is_new_visitor(day, kind, object_id, user_id):
    row = {'kind': kind, 'object_id': object_id, 'day': day, 'digest': _digest(day, kind, object_id, user_id)}
    try:
        with transaction.atomic():
            PageViewVisitor.objects.create(**row)
    except IntegrityError:
        return False
    return True


@safely
def record(request, kind, obj):
    """Compte la consultation d'une fiche par le membre connecté (méthode GET seulement)."""
    user = request.user
    if request.method != 'GET' or not user.is_authenticated or user.is_staff or user.is_superuser or _is_manager(user, kind, obj):
        return
    day = timezone.localdate()
    new_visitor = _is_new_visitor(day, kind, obj.pk, user.pk)
    increment(PageView, {'kind': kind, 'object_id': obj.pk, 'day': day}, views=1, visitors=int(new_visitor))


def purge_visitors(today=None):
    """Supprime les empreintes des jours passés (les compteurs de PageView, eux, restent). Renvoie le nombre de lignes supprimées."""
    return PageViewVisitor.objects.filter(day__lt=today or timezone.localdate()).delete()[0]
