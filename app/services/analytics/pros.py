"""Professionnels : brasseries et bars, revendications, complétude des fiches et prospects à démarcher.

C'est la page du modèle économique : combien d'établissements ont une fiche, combien ont un gérant, lesquels génèrent déjà de l'activité
sans que personne ne les représente (les premiers clients à contacter).
"""
from statistics import median

from django.db.models import Avg, Count, Q

from .formatting import fr
from ...models import Bar, Beer, BeerUser, Brewery, Drinks, EstablishmentClaim, ManagerInvitation, PageView
from ..members.roles import role_counts
from . import geo, page_views
from .bar_report import NEAR_BAR_M
from .blocks import Chart, Kpi, Note, Table
from .privacy import MIN_GROUP_SIZE, is_publishable
from .series import count_series, trend_chart
from .spots import spot_points

TOP = 15
HIDDEN = f'< {MIN_GROUP_SIZE}'
BEERS_PER_BREWERY = ((0, 0, 'Aucune bière'), (1, 2, '1 à 2'), (3, 5, '3 à 5'), (6, 10, '6 à 10'), (11, 10 ** 6, 'Plus de 10'))


def _percent(part, total):
    return round(part / total * 100, 1) if total else 0


def _coverage():
    """Part des fiches géolocalisées, avec gérant, vérifiées, avec SIRET : brasseries et bars côte à côte."""
    breweries, bars = Brewery.objects.all(), Bar.objects.all()
    totals = (breweries.count(), bars.count())

    def share(queryset, total, **lookup):
        return _percent(queryset.filter(**lookup).distinct().count(), total)

    metrics = (
        ('Avec un gérant', {'managers__isnull': False}),
        ('Vérifiées par l\'équipe', {'is_verified': True}),
        ('Géolocalisées', {'latitude__isnull': False, 'longitude__isnull': False}),
        ('Avec un SIRET', {'siret__isnull': False}),
    )
    return Chart('pro-coverage', 'Couverture des fiches établissements', 'bar', [name for name, _ in metrics],
                 [{'name': 'Brasseries', 'data': [share(breweries, totals[0], **lookup) for _, lookup in metrics]},
                  {'name': 'Bars', 'data': [share(bars, totals[1], **lookup) for _, lookup in metrics]}],
                 subtitle='% des fiches. « Avec un gérant » est le vivier de clients : chaque fiche sans gérant est une prospection possible')


def _completeness():
    fields = (('Téléphone', 'phone'), ('E-mail', 'email'), ('Site web', 'website'), ('Instagram', 'instagram'), ('Facebook', 'facebook'),
              ('Image', 'image'), ('Description', 'description'), ('Rue', 'street'))

    def filled(model, field):
        total = model.objects.count()
        return _percent(model.objects.exclude(**{f'{field}__isnull': True}).exclude(**{field: ''}).count(), total)

    return Chart('pro-completeness', 'Complétude des fiches', 'bar', [name for name, _ in fields],
                 [{'name': 'Brasseries', 'data': [filled(Brewery, field) for _, field in fields]},
                  {'name': 'Bars', 'data': [filled(Bar, field) for _, field in fields]}],
                 subtitle='Une fiche complète est plus utile aux membres et plus facile à vendre à son gérant')


def _claims(period):
    claims = EstablishmentClaim.objects.all()
    labels = dict(EstablishmentClaim.Status.choices)
    counts = {row['status']: row['n'] for row in claims.values('status').annotate(n=Count('pk'))}
    decided = [(c.decided_at - c.created_at).total_seconds() / 86400 for c in claims.filter(decided_at__isnull=False).only('created_at', 'decided_at')]
    approved, refused = counts.get('approved', 0), counts.get('rejected', 0)
    blocks = [
        Kpi('Revendications en attente', counts.get('pending', 0), hint='à examiner dans l\'administration'),
        Kpi('Taux d\'acceptation', f'{fr(_percent(approved, approved + refused))} %' if approved + refused else '—', hint=f'{approved} acceptée(s), {refused} refusée(s)'),
        Kpi('Délai médian de décision', f'{fr(median(decided), 1)} j' if decided else '—', hint='entre la demande et la réponse de l\'équipe'),
    ]
    if counts:
        blocks.append(Chart('claims-status', 'Revendications par statut', 'donut', [labels.get(k, k) for k in counts], [{'name': 'Demandes', 'data': list(counts.values())}]))
    series = count_series(claims, 'created_at', period)
    if any(series):
        blocks.append(trend_chart('claims-trend', 'Revendications déposées', series, period, unit_name='Revendications'))
    invitations = {row['status']: row['n'] for row in ManagerInvitation.objects.values('status').annotate(n=Count('pk'))}
    if invitations:
        invitation_labels = dict(ManagerInvitation.Status.choices)
        blocks.append(Chart('invitations-status', 'Invitations dans une équipe', 'donut', [invitation_labels.get(k, k) for k in invitations],
                            [{'name': 'Invitations', 'data': list(invitations.values())}], subtitle='Un gérant qui invite son équipe est un client engagé'))
    return blocks


def _catalogue_depth():
    counts = list(Brewery.objects.annotate(n=Count('beer', filter=Q(beer__is_deleted=False))).values_list('n', flat=True))
    data = [sum(1 for n in counts if low <= n <= high) for low, high, _ in BEERS_PER_BREWERY]
    return Chart('beers-per-brewery', 'Brasseries selon leur nombre de bières', 'donut', [label for *_x, label in BEERS_PER_BREWERY], [{'name': 'Brasseries', 'data': data}],
                 subtitle='Une brasserie sans bière n\'a rien à analyser : à compléter avant de la démarcher')


def _brewery_prospects(period):
    """Brasseries sans gérant, classées par activité : les plus bues d'abord. Données publiques, vue réservée à l'équipe."""
    activity = (Drinks.objects.filter(date__gte=period.start, beer__brewery__isnull=False, beer__brewery__managers__isnull=True).values('beer__brewery', 'beer__brewery__name')
                .annotate(n=Count('pk'), members=Count('drinker', distinct=True), avg=Avg('note')).order_by('-n')[:TOP])
    wishes = dict(Beer.objects.filter(is_deleted=False).values_list('brewery').annotate(w=Count('wishlisted_by')))
    views = page_views.by_object(period, PageView.Kind.BREWERY)
    rows = [[row['beer__brewery__name'], row['n'] if is_publishable(row['members']) else HIDDEN, row['members'] if is_publishable(row['members']) else HIDDEN,
             round(row['avg'], 2) if row['avg'] is not None else '—', wishes.get(row['beer__brewery'], 0),
             views[row['beer__brewery']][0] if row['beer__brewery'] in views and is_publishable(views[row['beer__brewery']][1]) else '—'] for row in activity]
    return Table('prospects-breweries', 'Brasseries à démarcher (sans gérant)', ['Brasserie', 'Dégustations', 'Dégustateurs', 'Note moyenne', 'Souhaits', 'Vues de la fiche'], rows,
                 subtitle='Activité déjà générée sur Pokebeer par des brasseries que personne ne représente : le meilleur argument de démarchage')


def _bar_prospects(period):
    bars = list(Bar.objects.filter(managers__isnull=True, latitude__isnull=False, longitude__isnull=False))
    points = spot_points(period)
    place_points = [(p.lat, p.lon, p) for p in points]
    rows = []
    for bar in bars:
        near = [p for _, _, p in geo.within_m((bar.latitude, bar.longitude), place_points, NEAR_BAR_M)]
        rows.append((bar.name, len(near), len({p.user_id for p in near})))
    rows.sort(key=lambda row: -row[1])
    return Table('prospects-bars', 'Bars à démarcher (sans gérant)', ['Bar', 'Lieux à proximité', 'Membres'],
                 [[name, spots if is_publishable(members) else HIDDEN, members if is_publishable(members) else HIDDEN] for name, spots, members in rows[:TOP]],
                 subtitle=f'Lieux de dégustation placés à moins de {NEAR_BAR_M} m du bar')


def _value_created(period):
    """Part des dégustations qui concernent une brasserie ayant déjà un gérant : la valeur que les gérants retrouvent déjà."""
    drinks = Drinks.objects.filter(date__gte=period.start)
    total = drinks.count()
    managed = drinks.filter(beer__brewery__managers__isnull=False).count()
    return Kpi('Dégustations de brasseries gérées', f'{fr(_percent(managed, total))} %', hint=f'{managed} sur {total} : le reste concerne des brasseries à convaincre')


def build(period, params):
    roles = role_counts(BeerUser.objects.all())
    blocks = [
        Kpi('Brasseries', Brewery.objects.count()),
        Kpi('Bars', Bar.objects.count()),
        Kpi('Comptes brasseur', roles['brewer']),
        Kpi('Comptes bartender', roles['bartender']),
        _value_created(period),
        _coverage(),
        *_claims(period),
        _brewery_prospects(period),
        _bar_prospects(period),
        page_views.top_table(period, PageView.Kind.BREWERY, 'top-brewery-views', 'Brasseries les plus consultées'),
        page_views.top_table(period, PageView.Kind.BAR, 'top-bar-views', 'Bars les plus consultés'),
        page_views.top_table(period, PageView.Kind.BEER, 'top-beer-views', 'Bières les plus consultées'),
        _completeness(),
        _catalogue_depth(),
        Note("Les vues des fiches ne sont comptées que depuis la mise en service de la mesure : les périodes plus anciennes sont à zéro."),
    ]
    return blocks
