"""Tirage du jour : cinq bières que le membre n'a pas encore goûtées, tirées selon leur rareté.

Un tirage par membre et par jour (jour local, voir `DailyDraw`), enregistré à l'ouverture : y revenir montre les mêmes cartes. La rareté
suit le nombre de dégustations de la bière (moins elle est goûtée, plus elle est rare ; règle dans domain/rarity.py). Les cartes sont
révélées de la plus commune à la plus rare. Une bière déjà vue lors d'un tirage précédent peut ressortir : le catalogue est petit.
"""
import random

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from ...domain import rarity
from ...models import Beer, DailyDraw, DailyDrawCard, Drinks, Notification
from ..members.achievements import check_and_notify_achievements, clear_feature_notifications
from .draw_reminders import TYPE as REMINDER_TYPE
from ..members.visibility import exclude_blocked

CARDS = 5

# État du tirage sur l'accueil
AVAILABLE, IN_PROGRESS, DONE, EXHAUSTED, DISABLED = 'available', 'in_progress', 'done', 'exhausted', 'disabled'
FEATURE = 'daily_draw_enabled'  # champ du membre : l'interrupteur de la fonctionnalité

_rng = random.SystemRandom()  # pas de séquence prévisible : ni rejouable, ni devinable


def _candidates(user):
    """Bières du catalogue visibles du membre qu'il n'a jamais goûtées (sous-requête : aucun identifiant de dégustation chargé)."""
    visible = exclude_blocked(Beer.objects.filter(is_deleted=False), user, 'added_by')
    return visible.exclude(id__in=Drinks.objects.filter(drinker=user).values('beer'))


def _tiers():
    """{palier: [identifiants]} sur tout le catalogue. Le classement ne dépend pas du membre : une bière a la même rareté pour tous.
    À égalité de dégustations, le slug (aléatoire, stable) départage."""
    ranked = (Beer.objects.filter(is_deleted=False).annotate(tastings=Count('drinks'))
              .order_by('-tastings', 'slug').values_list('id', flat=True))
    return rarity.split_ranking(list(ranked))


def pick(candidate_ids, tiers, rng=_rng, count=CARDS):
    """[(identifiant, palier)] de `count` bières distinctes, de la plus commune à la plus rare. Moins si le membre n'a plus assez à découvrir."""
    pool = {key: [beer_id for beer_id in ids if beer_id in candidate_ids] for key, ids in tiers.items()}
    picks = []
    while len(picks) < count:
        available = {key for key, ids in pool.items() if ids}
        if not available:
            break
        tier = rarity.pick_rarity(rng, available)
        ids = pool[tier.key]
        picks.append((ids.pop(rng.randrange(len(ids))), tier.key))
    order = {tier.key: index for index, tier in enumerate(rarity.RARITIES)}
    return sorted(picks, key=lambda pick_: order[pick_[1]])


def todays(user):
    """Le tirage d'aujourd'hui avec ses cartes, ou None s'il n'a pas encore été ouvert."""
    return (DailyDraw.objects.filter(user=user, day=timezone.localdate())
            .prefetch_related('cards__beer__brewery').first())


def open_today(user, rng=_rng):
    """Tirage d'aujourd'hui : le crée au premier appel, le renvoie tel quel ensuite. None s'il ne reste aucune bière à découvrir."""
    existing = todays(user)
    if existing:
        return existing
    picks = pick(set(_candidates(user).values_list('id', flat=True)), _tiers(), rng)
    if not picks:
        return None
    try:
        with transaction.atomic():
            draw = DailyDraw.objects.create(user=user)
            DailyDrawCard.objects.bulk_create(
                DailyDrawCard(draw=draw, beer_id=beer_id, rarity=tier, position=position) for position, (beer_id, tier) in enumerate(picks))
    except IntegrityError:
        pass  # deux clics simultanés : la contrainte d'unicité a gardé le premier tirage
    return todays(user)


def reveal(user, count):
    """Enregistre que le membre a retourné `count` cartes du tirage d'aujourd'hui (jamais moins que déjà enregistré, jamais plus que le tirage) :
    il reprend là où il s'est arrêté. Quand toutes le sont, le tirage est terminé. Renvoie le nombre de cartes retournées, ou None sans tirage."""
    draw = DailyDraw.objects.filter(user=user, day=timezone.localdate()).annotate(total=Count('cards')).first()
    if draw is None:
        return None
    count = max(0, min(count, draw.total))
    updated = DailyDraw.objects.filter(pk=draw.pk, revealed__lt=count).update(revealed=count)  # conditionnel : deux requêtes simultanées ne se défont pas
    if count == draw.total:
        DailyDraw.objects.filter(pk=draw.pk, completed_at__isnull=True).update(completed_at=timezone.now())
    if updated:
        check_and_notify_achievements(user)  # le trophée Découvreur compte chaque carte retournée
    return max(count, draw.revealed)


def home_state(user):
    """Ce que l'accueil propose : le bouton (AVAILABLE, IN_PROGRESS si les cartes n'ont pas toutes été révélées), l'attente du lendemain
    (DONE) ou rien (EXHAUSTED : le membre a tout goûté, DISABLED : il a désactivé la fonctionnalité)."""
    if not getattr(user, FEATURE):
        return DISABLED
    draw = DailyDraw.objects.filter(user=user, day=timezone.localdate()).only('completed_at').first()
    if draw:
        return DONE if draw.completed_at else IN_PROGRESS
    return AVAILABLE if _candidates(user).exists() else EXHAUSTED


def set_enabled(user, enabled):
    """Interrupteur du tirage du jour. Désactivé, le membre n'a plus ni bouton, ni rappel, ni trophée, et les notifications déjà reçues sur ce
    thème disparaissent ; réactivé, tout revient tel quel (sa progression au trophée est conservée)."""
    if getattr(user, FEATURE) != enabled:
        setattr(user, FEATURE, enabled)
        user.save(update_fields=[FEATURE])
    if not enabled:
        Notification.objects.filter(recipient=user, notif_type=REMINDER_TYPE).delete()
        clear_feature_notifications(user, FEATURE)
