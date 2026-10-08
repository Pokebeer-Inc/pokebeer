"""Revendication d'un établissement : qui peut gérer une brasserie ou un bar, et comment on s'en assure.

Rien n'est accordé automatiquement. Un membre qui se dit gérant dépose une demande avec le SIRET de l'établissement ; le SIRET est contrôlé
dans l'annuaire officiel (existence, établissement ouvert, activité cohérente : voir siret_registry), puis l'équipe accepte ou refuse. Seule
l'acceptation ajoute le membre aux gérants (et lui donne le rôle Brasseur / Bartender, par les signaux existants) et rattache le SIRET à la fiche.

Le SIRET reste sur la demande jusqu'à l'acceptation : le poser dès le dépôt permettrait de « réserver » le SIRET de quelqu'un d'autre.
"""
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import EstablishmentClaim
from ..validators import validate_siret
from . import beer_fields, catalog_matching, mailer, siret_registry
from .notifications import notify
from .places import PLACE_KINDS_BY_KEY
from .throttle import CLAIM_BY_USER

Status = EstablishmentClaim.Status


class ClaimError(Exception):
    """Demande impossible : le message est affichable tel quel, `field` désigne le champ concerné (par défaut aucun)."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


class ChoiceRequired(Exception):
    """Des fiches ressemblent à celle que le gérant veut créer : il doit dire laquelle est la sienne, ou confirmer qu'elle n'existe pas."""

    def __init__(self, report):
        super().__init__("Choix requis")
        self.report = report


@dataclass(frozen=True)
class RegistrationPlan:
    place: object        # fiche existante à revendiquer, ou None : une nouvelle fiche sera créée
    check: object        # siret_registry.SiretCheck


def normalize_siret(raw):
    siret = ''.join((raw or '').split())
    try:
        validate_siret(siret)
    except Exception as error:  # ValidationError : message déjà rédigé
        raise ClaimError(' '.join(getattr(error, 'messages', [str(error)])), field='siret') from None
    return siret


def is_manager(user, place):
    return place.managers.filter(pk=user.pk).exists()


def pending_claim(user, kind, place):
    return EstablishmentClaim.objects.filter(claimant=user, status=Status.PENDING, **{kind.key: place}).first()


def can_claim(user, kind, place):
    """Le bouton « Revendiquer cette fiche » est-il proposé à ce membre ?"""
    return user.is_authenticated and user.is_active and not is_manager(user, place) and pending_claim(user, kind, place) is None


def _place_url(kind, place):
    return f'{settings.PUBLIC_BASE_URL}{kind.detail_path(place)}'


def _email(user, subject, template, **context):
    mailer.send_templated(user.email, subject, template, {'user': user, **context})


def open_claim(user, kind, place, siret, message='', check=None):
    """Dépose la demande de `user` pour `place` (kind : PlaceKind). `check` : contrôle déjà fait du SIRET (inscription), sinon refait ici."""
    siret = normalize_siret(siret)
    if is_manager(user, place):
        raise ClaimError("Vous gérez déjà cette fiche.")
    if pending_claim(user, kind, place):
        raise ClaimError("Vous avez déjà une demande en cours pour cette fiche : l'équipe l'examine.")
    if CLAIM_BY_USER.exceeded(user.pk):
        raise ClaimError("Trop de demandes aujourd'hui, réessayez demain.")
    if place.siret and place.siret != siret:
        raise ClaimError("Cette fiche est rattachée à un autre SIRET : seul son titulaire peut la gérer.", field='siret')
    other = kind.model.objects.filter(siret=siret).exclude(pk=place.pk).first()
    if other:
        raise ClaimError(f"Erreur de SIRET", field='siret')
    check = check or siret_registry.check(siret, kind.key, place.name, place.postal_code)
    if check.rejection:
        raise ClaimError(check.rejection, field='siret')
    CLAIM_BY_USER.record(user.pk)
    try:
        with transaction.atomic():
            claim = EstablishmentClaim.objects.create(
                claimant=user, siret=siret, message=beer_fields.clean_text(message, 500) or '', registry=check.as_dict(), **{kind.key: place},
            )
    except IntegrityError:  # deux envois simultanés
        raise ClaimError("Vous avez déjà une demande en cours pour cette fiche : l'équipe l'examine.") from None
    # Les gérants actuels sont prévenus : si la demande n'est pas légitime, ils peuvent écrire à l'équipe
    notify('claim_received', place.managers.exclude(pk=user.pk), sender=user, **{kind.key: place})
    _email(user, "Votre demande de gestion est bien reçue", 'claim_received', place_name=place.name, place_url=_place_url(kind, place))
    return claim


def plan_registration(kind, name, postal_code, city, siret, choice=''):
    """Prépare l'inscription d'un gérant : contrôle le SIRET, puis cherche la fiche existante (même SIRET, ou même nom au même endroit).

    `choice` : réponse du gérant à ChoiceRequired, « existing:<slug> » (c'est cette fiche) ou « new:<jeton> » (elle n'existe pas encore).
    Lève ClaimError (SIRET refusé), ChoiceRequired (une fiche ressemble : à lui de dire).
    """
    siret = normalize_siret(siret)
    check = siret_registry.check(siret, kind.key, name, postal_code)
    if check.rejection:
        raise ClaimError(check.rejection, field='siret')
    holder = kind.model.objects.filter(siret=siret).first()
    if holder:
        return RegistrationPlan(holder, check)  # ce SIRET est déjà celui d'une fiche : c'est elle qu'on revendique
    report = catalog_matching.find_place(kind.key, name, postal_code, city)
    candidates = [c.obj for c in report.candidates if c.level >= catalog_matching.Level.PROBABLE]
    if not candidates:
        return RegistrationPlan(None, check)
    answer, _, value = (choice or '').partition(':')
    if answer == 'existing':
        chosen = next((c for c in candidates if c.slug == value), None)
        if chosen:
            return RegistrationPlan(chosen, check)
    elif answer == 'new' and catalog_matching.confirmed(report, value):
        return RegistrationPlan(None, check)
    raise ChoiceRequired(report)


def _lock(claim):
    # Seule la demande est verrouillée (les fiches jointes sont facultatives : PostgreSQL refuse de verrouiller le côté nul d'une jointure)
    locked = EstablishmentClaim.objects.select_for_update(of=('self',)).select_related('brewery', 'bar', 'claimant').get(pk=claim.pk)
    if locked.status != Status.PENDING:
        raise ClaimError("Cette demande a déjà été traitée.")
    return locked


def _announce(claim, kind, approved):
    place = claim.place
    notify('claim_approved' if approved else 'claim_rejected', [claim.claimant], sender=claim.decided_by, text_content=None if approved else claim.reason, **{kind.key: place})
    if approved:
        _email(claim.claimant, "Votre établissement est à vous sur Pokebeer", 'claim_approved', place_name=place.name, place_url=_place_url(kind, place))
    else:
        _email(claim.claimant, "Votre demande de gestion a été refusée", 'claim_rejected', place_name=place.name, reason=claim.reason)


def approve(claim, by):
    """Accepte la demande : le membre devient gérant et le SIRET est rattaché à la fiche."""
    with transaction.atomic():
        claim = _lock(claim)
        kind = PLACE_KINDS_BY_KEY[claim.kind_key]
        place = claim.place
        if not claim.claimant.is_active:
            raise ClaimError("Le compte du demandeur est suspendu.")
        if not place.siret:
            if kind.model.objects.filter(siret=claim.siret).exclude(pk=place.pk).exists():
                raise ClaimError("Ce SIRET est déjà rattaché à une autre fiche : fusionnez d'abord les doublons.")
            place.siret = claim.siret
            place.save(update_fields=['siret'])
        elif place.siret != claim.siret:
            raise ClaimError("Cette fiche est rattachée à un autre SIRET.")
        place.managers.add(claim.claimant)
        claim.status, claim.decided_by, claim.decided_at = Status.APPROVED, by, timezone.now()
        claim.save(update_fields=['status', 'decided_by', 'decided_at'])
        transaction.on_commit(lambda: _announce(claim, kind, approved=True))
    return claim


def reject(claim, by, reason):
    """Refuse la demande ; le motif est communiqué au demandeur."""
    reason = beer_fields.clean_text(reason, 300)
    if not reason:
        raise ClaimError("Indiquez le motif du refus : il est communiqué au demandeur.")
    with transaction.atomic():
        claim = _lock(claim)
        claim.status, claim.reason, claim.decided_by, claim.decided_at = Status.REJECTED, reason, by, timezone.now()
        claim.save(update_fields=['status', 'reason', 'decided_by', 'decided_at'])
        transaction.on_commit(lambda: _announce(claim, PLACE_KINDS_BY_KEY[claim.kind_key], approved=False))
    return claim


def cancel(claim, user):
    """Le demandeur retire sa demande."""
    with transaction.atomic():
        claim = _lock(claim)
        if claim.claimant_id != user.pk:
            raise ClaimError("Cette demande n'est pas la vôtre.")
        claim.status, claim.decided_at = Status.CANCELLED, timezone.now()
        claim.save(update_fields=['status', 'decided_at'])
    return claim


def pending_count():
    return EstablishmentClaim.objects.filter(status=Status.PENDING).count()
