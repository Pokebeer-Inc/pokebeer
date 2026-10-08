"""Campagnes e-mail rédigées dans l'administration : audience, lancement, envoi par lots.

- Promotionnel : tous les membres actifs sauf les désinscrits, avec lien de désinscription dans chaque e-mail.
- Alerte obligatoire : tous les membres actifs, quel que soit leur choix (sécurité, obligation légale, compte).
- Le lancement fige la liste des destinataires ; l'envoi se poursuit par lots (tâche quotidienne ou bouton de l'admin), dans la
  limite du quota du jour, et revérifie la désinscription au moment d'écrire à chacun : un désabonnement prend effet immédiatement.
- Chaque destinataire est réservé avant l'envoi : au pire un membre est ignoré après un incident, jamais écrit deux fois.
"""
import re
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from ..models import BeerUser, CampaignRecipient, EmailCampaign
from . import app_links, mailer, marketing
from .throttle import CAMPAIGN_EMAIL_GLOBAL, CAMPAIGN_LAUNCH

Kind, Audience, Status = EmailCampaign.Kind, EmailCampaign.Audience, EmailCampaign.Status
Delivery = CampaignRecipient.Status

GLOBAL_KEY = 'all'
CHUNK = 500
ADMIN_BATCH = 25  # taille d'un lot déclenché depuis l'administration (la requête doit rester courte)
MAX_CUSTOM_MEMBERS = 500
TEST_PREFIX = "[TEST] "


class CampaignError(Exception):
    """Opération impossible dans l'état actuel de la campagne (message affichable à l'administrateur)."""


class TooManyLaunches(CampaignError):
    pass


@dataclass(frozen=True)
class AudiencePreview:
    recipients: int          # membres qui recevront le message
    no_consent: int          # membres de l'audience écartés parce que désinscrits des e-mails promotionnels


def _audience(campaign):
    """Membres actifs visés par les critères de la campagne, avant d'écarter les désinscrits."""
    members = BeerUser.objects.filter(is_active=True)
    if campaign.audience in (Audience.ACTIVE, Audience.INACTIVE):
        limit = timezone.now() - timedelta(days=campaign.activity_days)
        members = members.filter(last_activity_at__gte=limit) if campaign.audience == Audience.ACTIVE else members.filter(last_activity_at__lt=limit)
    elif campaign.audience == Audience.CUSTOM:
        members = members.filter(pk__in=campaign.custom_members.values('pk'))
    return members


def _consenting(members, kind):
    return members.filter(marketing_opt_in=True) if kind == Kind.PROMOTIONAL else members


def audience_for(campaign):
    """Membres qui recevront la campagne."""
    return _consenting(_audience(campaign), campaign.kind)


def preview(campaign):
    members = _audience(campaign)
    recipients = _consenting(members, campaign.kind).count()
    return AudiencePreview(recipients=recipients, no_consent=members.count() - recipients)


def stats(campaign):
    """Répartition des envois par état, pour l'administration."""
    counts = dict(campaign.recipients.values_list('status').annotate(total=Count('pk')))
    return {label: counts.get(value, 0) for value, label in Delivery.choices} | {'total': sum(counts.values())}


def launch(campaign, by):
    """Fige les destinataires et passe la campagne en envoi. L'envoi lui-même suit par lots (send_batch)."""
    if CAMPAIGN_LAUNCH.exceeded(GLOBAL_KEY):
        raise TooManyLaunches("Plusieurs campagnes viennent d'être lancées : attendez avant d'en lancer une autre.")
    with transaction.atomic():
        campaign = EmailCampaign.objects.select_for_update().get(pk=campaign.pk)
        if campaign.status != Status.DRAFT:
            raise CampaignError("Cette campagne n'est plus un brouillon.")
        ids = list(audience_for(campaign).values_list('pk', flat=True))
        if not ids:
            raise CampaignError("Aucun destinataire : l'audience est vide (ou tous les membres visés sont désinscrits).")
        for start in range(0, len(ids), CHUNK):
            CampaignRecipient.objects.bulk_create(
                [CampaignRecipient(campaign=campaign, user_id=pk) for pk in ids[start:start + CHUNK]], ignore_conflicts=True,
            )
        campaign.status, campaign.launched_at, campaign.launched_by = Status.SENDING, timezone.now(), by
        campaign.save(update_fields=['status', 'launched_at', 'launched_by'])
        campaign.custom_members.clear()  # donnée devenue inutile : les destinataires sont figés dans CampaignRecipient
    CAMPAIGN_LAUNCH.record(GLOBAL_KEY)
    return campaign


def cancel(campaign):
    """Arrête l'envoi : les messages déjà partis le restent, les autres destinataires sont ignorés."""
    with transaction.atomic():
        campaign = EmailCampaign.objects.select_for_update().get(pk=campaign.pk)
        if campaign.status not in (Status.DRAFT, Status.SENDING):
            raise CampaignError("Cette campagne est déjà terminée.")
        campaign.recipients.filter(status=Delivery.PENDING).update(status=Delivery.SKIPPED)
        campaign.status, campaign.finished_at = Status.CANCELLED, timezone.now()
        campaign.save(update_fields=['status', 'finished_at'])


def _still_eligible(campaign, user):
    """Au moment d'écrire : compte toujours actif et, pour un promotionnel, membre toujours non désinscrit."""
    return user.is_active and (not campaign.is_promotional or user.marketing_opt_in)


def email_context(campaign, user):
    """Variables des gabarits emails/campaign.* pour ce membre (le texte reste du texte : le gabarit HTML l'échappe)."""
    paragraphs = [paragraph.strip().replace('{username}', user.username) for paragraph in re.split(r'\n\s*\n', campaign.body) if paragraph.strip()]
    return {
        'user': user, 'paragraphs': paragraphs, 'cta_label': campaign.cta_label, 'cta_url': campaign.cta_url,
        'promotional': campaign.is_promotional, 'preferences_url': marketing.preferences_url(user),
        'support_email': settings.SUPPORT_EMAIL, 'base_url': settings.PUBLIC_BASE_URL,
    }


def _deliver(campaign, user, subject=None):
    headers = marketing.unsubscribe_headers(user) if campaign.is_promotional else None
    return mailer.send_templated(user.email, subject or campaign.subject, 'campaign', email_context(campaign, user), headers=headers)


def send_test(campaign, to_user):
    """Aperçu réel envoyé à l'administrateur lui-même, sans condition de consentement ni de quota de campagne."""
    return _deliver(campaign, to_user, subject=TEST_PREFIX + campaign.subject)


def send_batch(campaign, limit=None):
    """Envoie la suite de la campagne dans la limite du quota du jour (et de `limit`) ; renvoie le nombre d'e-mails envoyés."""
    if campaign.status != Status.SENDING:
        return 0
    sent = 0
    pending = campaign.recipients.filter(status=Delivery.PENDING).select_related('user').order_by('pk')
    for recipient in pending.iterator(chunk_size=CHUNK):
        if CAMPAIGN_EMAIL_GLOBAL.exceeded(GLOBAL_KEY) or (limit is not None and sent >= limit):
            return sent
        if not CampaignRecipient.objects.filter(pk=recipient.pk, status=Delivery.PENDING).update(status=Delivery.SENDING):
            continue  # pris en charge par un autre envoi en parallèle
        if not _still_eligible(campaign, recipient.user):
            CampaignRecipient.objects.filter(pk=recipient.pk).update(status=Delivery.SKIPPED)
            continue
        CAMPAIGN_EMAIL_GLOBAL.record(GLOBAL_KEY)
        ok = _deliver(campaign, recipient.user)
        CampaignRecipient.objects.filter(pk=recipient.pk).update(
            status=Delivery.SENT if ok else Delivery.FAILED, sent_at=timezone.now() if ok else None,
        )
        sent += ok
    # Plus rien en attente : la campagne est terminée (sauf si un autre envoi a été annulé entre-temps)
    if not campaign.recipients.filter(status=Delivery.PENDING).exists():
        EmailCampaign.objects.filter(pk=campaign.pk, status=Status.SENDING).update(status=Status.DONE, finished_at=timezone.now())
    return sent


def send_pending(limit=None):
    """Tâche quotidienne : poursuit les campagnes en cours, la plus ancienne d'abord, jusqu'au quota du jour."""
    sent = 0
    for campaign in EmailCampaign.objects.filter(status=Status.SENDING).order_by('launched_at'):
        sent += send_batch(campaign, None if limit is None else limit - sent)
        if CAMPAIGN_EMAIL_GLOBAL.exceeded(GLOBAL_KEY):
            break
    return sent
