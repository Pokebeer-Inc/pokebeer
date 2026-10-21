"""Engagement : le membre revient-il, utilise-t-il l'application, répond-il aux notifications ? Santé du produit, côté membres.

Deux sources : `last_activity_at` (dernière visite de chaque membre, valable depuis toujours) et `ActivityDay` (un jour d'activité par membre, depuis
la mise en service de la mesure) qui donne les vrais actifs quotidiens, hebdomadaires et mensuels, et la rétention par visites.
"""
from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Count, Exists, F, Min, OuterRef, Q, Sum
from django.utils import timezone

from .formatting import fr
from ...models import ActivityDay, BeerDraft, BeerUser, Drinks, DrinkReaction, Notification, QuotaUsage, UserFollow
from .blocks import Chart, Kpi, Note, Table
from .date import date_range
from .habits import retention_table
from .series import count_series, trend_chart

MIN_NOTIFICATIONS = 5
RECENCY_BUCKETS = ((0, 7, 'Actifs (moins de 7 jours)'), (7, 30, '7 à 30 jours'), (30, 90, '30 à 90 jours'), (90, 180, '3 à 6 mois'),
                   (180, None, 'Plus de 6 mois'))
FIRST_TASTING_BUCKETS = ((None, 0, 'Le jour même'), (1, 7, 'Dans la semaine'), (8, 30, 'Dans le mois'), (31, 10 ** 6, 'Plus tard'))
FOLLOWER_BUCKETS = ((0, 0, 'Aucun abonné'), (1, 5, '1 à 5'), (6, 20, '6 à 20'), (21, 10 ** 6, 'Plus de 20'))
SCOPE_LABELS = {'chat': 'Chat (Gaétan)', 'label': 'Lecture d\'étiquette', 'ean': 'Code-barres', 'photo': 'Photo'}
PREFERENCES = (
    ('notif_global', 'Toutes les notifications'), ('notif_follow', 'Nouveaux abonnés'), ('notif_social', 'Interactions'),
    ('notif_network', 'Réseau'), ('notif_achievements', 'Trophées'), ('notif_establishment', 'Établissements'),
)


def _percent(part, total):
    return round(part / total * 100, 1) if total else 0


def _recency(members, now):
    counts = []
    for low, high, _label in RECENCY_BUCKETS:
        window = members.filter(last_activity_at__lte=now - timedelta(days=low))
        counts.append((window.filter(last_activity_at__gt=now - timedelta(days=high)) if high else window).count())
    return Chart('recency', 'Ancienneté de la dernière visite', 'donut', [label for *_x, label in RECENCY_BUCKETS], [{'name': 'Membres', 'data': counts}],
                 subtitle='Les membres à 30-90 jours sont ceux à relancer avant qu\'ils ne partent (voir les campagnes e-mail)')


LEGACY_UNTIL_DAYS = 30


def _history_days(today):
    """Nombre de jours couverts par les jours d'activité (0 sans aucune ligne)."""
    since = ActivityDay.objects.aggregate(first=Min('day'))['first']
    return (today - since).days + 1 if since else 0


def _visits(period):
    """Actifs quotidiens, hebdomadaires et mensuels d'après les jours d'activité, courbe par intervalle et rétention par visites."""
    since = ActivityDay.objects.aggregate(first=Min('day'))['first']
    if since is None:
        return [Note("Aucun jour d'activité enregistré pour l'instant : la mesure se remplit à chaque visite d'un membre connecté.")]
    today = period.today
    visits = ActivityDay.objects.all()

    def distinct_since(days):
        return visits.filter(day__gte=today - timedelta(days=days - 1)).values('user').distinct().count()

    yesterday = visits.filter(day=today - timedelta(days=1)).count()
    weekly, monthly = distinct_since(7), distinct_since(30)
    span = min(30, (today - since).days)
    daily = visits.filter(day__gte=today - timedelta(days=span), day__lt=today).values('day').annotate(n=Count('user')).values_list('n', flat=True) if span else []
    average = sum(daily) / span if span else 0
    blocks = [
        Kpi('Actifs hier (DAU)', yesterday, hint=f'mesure disponible depuis le {since:%d/%m/%Y}'),
        Kpi('Actifs sur 7 jours (WAU)', weekly),
        Kpi('Actifs sur 30 jours (MAU)', monthly),
        Kpi('Stickiness (DAU moyen / MAU)', f'{fr(_percent(average, monthly))} %' if monthly else '—',
            hint=f'part des actifs du mois présents un jour donné, sur {span} jour(s) complet(s) ; 20 % est un bon niveau pour une application sociale'),
    ]
    series = count_series(visits, 'day', period, Count('user', distinct=True))
    blocks.append(trend_chart('active-visits', 'Membres actifs (au moins une visite)', series, period, unit_name='Membres actifs', band=True,
                              subtitle='Visites de membres connectés, pas seulement les dégustations : la vraie mesure d\'audience'))
    blocks.append(retention_table(period, (visits, 'user', 'day'), 'retention-visits', 'Rétention par visites',
                                  'Part des inscrits d\'un mois revenus au moins un jour M+0, M+1, M+2, M+3 (jours d\'activité enregistrés seulement)'))
    return blocks


def _activation(period):
    cohort = BeerUser.objects.filter(created_at__date__gte=period.start)
    total = cohort.count()
    if not total:
        return []
    steps = [
        ('Inscription', total),
        ('Inscription terminée (âge, genre)', cohort.filter(onboarding_done=True).count()),
        ('1ère dégustation', cohort.filter(drinks__isnull=False).distinct().count()),
        ('5 dégustations ou plus', cohort.annotate(n=Count('drinks')).filter(n__gte=5).count()),
        ('Commente un avis', cohort.filter(drinks__comment__gt='').distinct().count()),
        ('Suit un membre', cohort.filter(following__isnull=False).distinct().count()),
        ('Place un lieu', cohort.filter(spots__isnull=False).distinct().count()),
        ('Utilise la liste « À goûter »', cohort.filter(wishlist_beers__isnull=False).distinct().count()),
    ]
    chart = Chart('activation', 'Parcours d\'activation des nouveaux membres', 'hbar', [label for label, _ in steps],
                  [{'name': '% des inscrits', 'data': [_percent(n, total) for _, n in steps]}],
                  subtitle=f'{total} inscrit(s) sur la période : où se perdent-ils entre l\'inscription et un usage régulier ?')

    # Délai avant la première dégustation (date déclarée : une dégustation antidatée compte comme « le jour même »)
    firsts = (Drinks.objects.filter(drinker__in=cohort).values('drinker', created=F('drinker__created_at__date')).annotate(first=Min('date')))
    counts = Counter()
    for row in firsts:
        delay = max(0, (row['first'] - row['created']).days)
        counts[next(label for low, high, label in FIRST_TASTING_BUCKETS if (low is None or delay >= low) and delay <= high)] += 1
    never = total - sum(counts.values())
    labels = [label for *_x, label in FIRST_TASTING_BUCKETS] + ['Jamais']
    delay_chart = Chart('first-tasting-delay', 'Délai avant la première dégustation', 'donut', labels,
                        [{'name': 'Nouveaux membres', 'data': [counts[label] for label in labels[:-1]] + [never]}],
                        subtitle='Un membre qui ne note rien dans la première semaine revient rarement')
    return [chart, delay_chart]


def _notifications(period):
    since = date_range(Notification.objects.all(), 'created_at', period.start)
    labels = dict(Notification.NOTIFICATION_TYPES)
    rows = since.values('notif_type').annotate(n=Count('pk'), read=Count('pk', filter=Q(is_read=True))).order_by('-n')
    table = [[labels.get(r['notif_type'], r['notif_type']), r['n'], f"{fr(_percent(r['read'], r['n']))} %"] for r in rows if r['n'] >= MIN_NOTIFICATIONS]
    return Table('notifications', 'Notifications : envoyées et lues', ['Type', 'Envoyées', 'Lues'], table,
                 subtitle=f'Types avec au moins {MIN_NOTIFICATIONS} envois ; un taux bas signale un type inutile ou mal ciblé')


def _preferences(members):
    total = members.count()
    if not total:
        return []
    disabled = [(label, members.filter(**{field: False}).count()) for field, label in PREFERENCES]
    return [Chart('notif-optout', 'Notifications désactivées par les membres', 'hbar', [label for label, _ in disabled],
                  [{'name': '% des membres', 'data': [_percent(n, total) for _, n in disabled]}],
                  subtitle='Une catégorie très désactivée est trop bavarde')]


def _quota_usage(members, period):
    usage = date_range(QuotaUsage.objects.all(), 'day', period.start)
    by_scope = defaultdict(lambda: defaultdict(int))
    for row in usage.annotate(bucket=period.trunc('day')).values('bucket', 'scope').annotate(total=Sum('count')):
        by_scope[row['scope']][row['bucket'].date() if hasattr(row['bucket'], 'date') else row['bucket']] += row['total']
    if not by_scope:
        return []
    buckets = period.buckets()
    blocks = [Chart('ai-usage', 'Appels aux services IA et scan', 'bar', [period.label(b) for b in buckets],
                    [{'name': SCOPE_LABELS.get(scope, scope), 'data': [by_scope[scope].get(b, 0) for b in buckets]} for scope in by_scope],
                    stacked=True, subtitle='Chat, lecture d\'étiquette et code-barres : suit l\'adoption ET le coût des services payants')]
    total = members.count()
    adopters = {row['scope']: row['n'] for row in usage.values('scope').annotate(n=Count('user', distinct=True))}
    blocks.append(Chart('ai-adoption', 'Membres ayant utilisé chaque service', 'hbar', [SCOPE_LABELS.get(s, s) for s in adopters],
                        [{'name': '% des membres actifs', 'data': [_percent(n, total) for n in adopters.values()]}],
                        subtitle='Un service peu utilisé coûte pour rien ; un service très utilisé justifie une offre payante'))
    return blocks


def _social(members, period):
    blocks = []
    follows = count_series(UserFollow.objects.all(), 'created_at', period)
    if any(follows):
        blocks.append(trend_chart('follows', 'Nouveaux abonnements', follows, period, unit_name='Abonnements'))
    counts = [0] * len(FOLLOWER_BUCKETS)
    for followers in members.annotate(f=Count('followers')).values_list('f', flat=True):
        for index, (low, high, _label) in enumerate(FOLLOWER_BUCKETS):
            if low <= followers <= high:
                counts[index] += 1
                break
    blocks.append(Chart('followers', 'Membres selon leur nombre d\'abonnés', 'donut', [label for *_x, label in FOLLOWER_BUCKETS], [{'name': 'Membres', 'data': counts}],
                        subtitle='Mesure la densité du réseau social : un réseau dense retient mieux'))
    reactions = defaultdict(lambda: [0, 0])
    for row in (date_range(DrinkReaction.objects.all(), 'created_at', period.start).annotate(bucket=period.trunc('created_at'))
                .values('bucket', 'is_like').annotate(n=Count('pk'))):
        reactions[row['bucket'].date() if hasattr(row['bucket'], 'date') else row['bucket']][0 if row['is_like'] else 1] += row['n']
    if reactions:
        buckets = period.buckets()
        blocks.append(Chart('reactions', 'Pouces sur les avis', 'bar', [period.label(b) for b in buckets],
                            [{'name': 'Pouces en l\'air', 'data': [reactions[b][0] for b in buckets]}, {'name': 'Pouces en bas', 'data': [reactions[b][1] for b in buckets]}],
                            stacked=True, subtitle='Participation à la communauté ; un ratio de pouces en bas élevé signale des avis contestés'))
    return blocks


def _richness(period):
    """Part des dégustations enrichies (commentaire, photo, lieu, prix), par intervalle : la qualité des données qu'on pourra vendre."""
    has_photo = Q(photo__isnull=False) & ~Q(photo='')
    metrics = (('Commentaire', Q(comment__gt='')), ('Photo', has_photo), ('Lieu', ~Q(venue_type='')), ('Prix', Q(price__isnull=False)))
    rows = (date_range(Drinks.objects.all(), 'date', period.start).annotate(bucket=period.trunc('date')).values('bucket')
            .annotate(total=Count('pk'), **{f'm{i}': Count('pk', filter=cond) for i, (_n, cond) in enumerate(metrics)}))
    by_bucket = {(row['bucket'].date() if hasattr(row['bucket'], 'date') else row['bucket']): row for row in rows}
    if not by_bucket:
        return []
    buckets = period.buckets()
    series = [{'name': name, 'data': [_percent(by_bucket[b][f'm{i}'], by_bucket[b]['total']) if b in by_bucket else None for b in buckets]}
              for i, (name, _c) in enumerate(metrics)]
    return [Chart('richness', 'Richesse des avis dans le temps', 'line', [period.label(b) for b in buckets], series,
                  subtitle='% de dégustations avec chaque information : la valeur des données revendues dépend de ces taux')]


def _wishlist_conversion():
    through = BeerUser.wishlist_beers.through
    total = through.objects.filter(beer__is_deleted=False).count()
    if not total:
        return []
    tasted = through.objects.filter(beer__is_deleted=False).filter(
        Exists(Drinks.objects.filter(drinker_id=OuterRef('beeruser_id'), beer_id=OuterRef('beer_id')))).count()
    return [Kpi('Souhaits devenus dégustations', f'{fr(_percent(tasted, total))} %', hint=f'{tasted} sur {total} bières « à goûter » ont ensuite été notées')]


def _drafts():
    rows = BeerDraft.objects.values('current_step').annotate(n=Count('pk')).order_by('current_step')
    data = {row['current_step']: row['n'] for row in rows}
    if not data:
        return []
    steps = list(range(1, max(data) + 1))
    return [Chart('draft-steps', 'Ajouts de bière abandonnés, par étape', 'bar', [f'Étape {s}' for s in steps],
                  [{'name': 'Brouillons en cours', 'data': [data.get(s, 0) for s in steps]}],
                  subtitle='Où les membres quittent le formulaire d\'ajout : une étape très chargée est à simplifier')]


def build(period, params):
    now = timezone.now()
    members = BeerUser.objects.filter(is_active=True)
    total = members.count()
    active = {days: members.filter(last_activity_at__gte=now - timedelta(days=days)).count() for days in (7, 30, 90)}
    # Tant que les jours d'activité couvrent moins de 30 jours, la dernière visite de chaque membre reste la seule mesure sur 7 et 30 jours ;
    # ensuite DAU, WAU et MAU (plus bas) la remplacent : deux séries de « actifs sur 7 jours » côte à côte se contrediraient.
    legacy = [
        Kpi('Actifs sur 7 jours (dernière visite)', active[7], hint=f'{fr(_percent(active[7], total))} % des membres actifs'),
        Kpi('Actifs sur 30 jours (dernière visite)', active[30], hint=f'{fr(_percent(active[30], total))} % des membres actifs'),
        Kpi('Ratio 7 jours / 30 jours', f'{fr(_percent(active[7], active[30]))} %', hint='indicateur de régularité : plus il est haut, plus les membres reviennent souvent'),
    ] if _history_days(period.today) < LEGACY_UNTIL_DAYS else []
    blocks = [
        *legacy,
        Kpi('Actifs sur 90 jours (dernière visite)', active[90], hint=f'{fr(_percent(active[90], total))} % des membres actifs'),
        Kpi('Notifications push (Android)', f'{fr(_percent(members.filter(fcm_token__isnull=False).exclude(fcm_token="").count(), total))} %', hint='membres avec un appareil enregistré'),
        Kpi('E-mails promotionnels acceptés', f'{fr(_percent(members.filter(marketing_opt_in=True).count(), total))} %', hint='audience joignable par campagne'),
        *_wishlist_conversion(),
        _recency(members, now),
        *_visits(period),
        *_activation(period),
        *_richness(period),
        *_social(members, period),
        *_quota_usage(members, period),
        _notifications(period),
        *_preferences(members),
        *_drafts(),
    ]
    return blocks
