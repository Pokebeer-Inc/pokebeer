"""Communauté : signalements, modération, échanges avec l'équipe, campagnes e-mail, départs. Pilotage interne, pas de donnée commerciale.

Aucun membre n'est nommé ici : seulement des volumes, des taux et des délais.
"""
from collections import Counter
from statistics import median

from django.db.models import Count, F, Min

from .formatting import fr
from ...models import AccountDeletion, CampaignRecipient, EmailCampaign, Feedback, FeedbackMessage, ModerationEntry, Report, UserBlock
from .blocks import Chart, Kpi, Table
from .date import date_range
from .series import count_series, trend_chart


def _percent(part, total):
    return round(part / total * 100, 1) if total else 0


def _days(seconds):
    return f'{fr(seconds / 86400, 1)} j' if seconds is not None else '—'


def _reports(period):
    reports = date_range(Report.objects.all(), 'created_at', period.start)
    blocks = []
    reasons = dict(Report.REASON_CHOICES)
    by_reason = reports.values('reason').annotate(n=Count('pk')).order_by('-n')
    if by_reason:
        blocks.append(Chart('report-reasons', 'Signalements par motif', 'donut', [reasons.get(r['reason'], r['reason']) for r in by_reason],
                            [{'name': 'Signalements', 'data': [r['n'] for r in by_reason]}]))
    targets = Counter()
    for field, label in (('reported_beer', 'Bière'), ('reported_drink', 'Avis'), ('reported_user', 'Membre'), ('reported_brewery', 'Brasserie')):
        targets[label] = reports.filter(**{f'{field}__isnull': False}).count()
    if any(targets.values()):
        blocks.append(Chart('report-targets', 'Signalements par cible', 'donut', list(targets), [{'name': 'Signalements', 'data': list(targets.values())}],
                            subtitle='Ce que la communauté juge problématique : avis, membres, fiches'))
    series = count_series(Report.objects.all(), 'created_at', period)
    if any(series):
        blocks.append(trend_chart('report-trend', 'Signalements dans le temps', series, period, unit_name='Signalements'))
    pending = Report.objects.exclude(status='resolved').count()
    return [Kpi('Signalements à traiter', pending, hint='envoyés ou en cours d\'examen'), *blocks]


def _moderation(period):
    entries = date_range(ModerationEntry.objects.all(), 'created_at', period.start)
    kinds = dict(ModerationEntry.Kind.choices)
    actions = dict(ModerationEntry.Action.choices)
    rows = entries.values('kind', 'action').annotate(n=Count('pk')).order_by('-n')
    blocks = []
    if rows:
        blocks.append(Chart('moderation-mix', 'Contenus soumis à la modération', 'hbar', [f"{kinds.get(r['kind'], r['kind'])} · {actions.get(r['action'], r['action'])}" for r in rows],
                            [{'name': 'Entrées', 'data': [r['n'] for r in rows]}]))
    reviewed = list(entries.filter(reviewed_at__isnull=False).values_list('created_at', 'reviewed_at'))
    delays = [(done - created).total_seconds() for created, done in reviewed]
    suggestions = ModerationEntry.objects.suggestions().exclude(outcome='')
    applied = suggestions.filter(outcome='applied').count()
    blocks += [
        Kpi('Contenus à valider', ModerationEntry.objects.pending().count()),
        Kpi('Délai médian de relecture', _days(median(delays)) if delays else '—'),
        Kpi('Suggestions acceptées', f'{fr(_percent(applied, suggestions.count()))} %' if suggestions.exists() else '—',
            hint='part des suggestions de modification appliquées : mesure la qualité des contributions'),
    ]
    return blocks


def _support(period):
    feedbacks = date_range(Feedback.objects.all(), 'created_at', period.start)
    total = feedbacks.count()
    first_reply = (FeedbackMessage.objects.filter(author_kind=FeedbackMessage.Author.TEAM, feedback__in=feedbacks)
                   .values('feedback', created=F('feedback__created_at')).annotate(reply=Min('created_at')))
    delays = [(row['reply'] - row['created']).total_seconds() for row in first_reply]
    return [
        Kpi('Messages à l\'équipe', total, hint='sur la période'),
        Kpi('Délai médian de première réponse', _days(median(delays)) if delays else '—'),
        Kpi('Sans réponse', feedbacks.filter(status='pending').count(), hint='échanges en attente de l\'équipe'),
    ]


def _campaigns():
    labels = dict(CampaignRecipient.Status.choices)
    rows = []
    for campaign in EmailCampaign.objects.exclude(status=EmailCampaign.Status.DRAFT)[:10]:
        counts = {r['status']: r['n'] for r in campaign.recipients.values('status').annotate(n=Count('pk'))}
        total = sum(counts.values())
        rows.append([campaign.subject, campaign.get_status_display(), total, counts.get('sent', 0), counts.get('failed', 0), counts.get('skipped', 0),
                     f"{fr(_percent(counts.get('sent', 0), total))} %"])
    return Table('campaigns', 'Campagnes e-mail', ['Objet', 'Statut', 'Destinataires', labels['sent'], labels['failed'], labels['skipped'], 'Taux d\'envoi'], rows,
                 subtitle='« Ignoré » : désinscrit ou suspendu avant l\'envoi. L\'ouverture et le clic ne sont pas mesurés.')


def _departures(period):
    deletions = date_range(AccountDeletion.objects.all(), 'deleted_at', period.start)
    reasons = dict(AccountDeletion.Reason.choices)
    by_reason = deletions.values('reason').annotate(n=Count('pk')).order_by('-n')
    blocks = []
    if by_reason:
        blocks.append(Chart('deletion-reasons', 'Comptes supprimés par motif', 'donut', [reasons.get(r['reason'], r['reason']) for r in by_reason],
                            [{'name': 'Comptes', 'data': [r['n'] for r in by_reason]}]))
    inactivity = deletions.filter(reason=AccountDeletion.Reason.INACTIVITY)
    warned = inactivity.filter(was_warned=True).count()
    if inactivity.exists():
        blocks.append(Kpi('Inactifs prévenus avant suppression', f'{fr(_percent(warned, inactivity.count()))} %', hint='un inactif prévenu qui revient n\'est pas supprimé'))
    series = count_series(AccountDeletion.objects.all(), 'deleted_at', period)
    if any(series):
        blocks.append(trend_chart('deletion-trend', 'Suppressions de compte dans le temps', series, period, unit_name='Comptes supprimés'))
    return blocks


def build(period, params):
    blocks = [
        *_reports(period),
        *_moderation(period),
        *_support(period),
        Kpi('Blocages entre membres', date_range(UserBlock.objects.all(), 'created_at', period.start).count(), hint='sur la période : un pic signale un problème de comportement'),
        _campaigns(),
        *_departures(period),
    ]
    return blocks
