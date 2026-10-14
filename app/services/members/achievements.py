"""Trophées des membres : calcul des paliers et notifications de progression."""
from dataclasses import dataclass
from functools import cached_property
from collections.abc import Callable

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Max, Q
from django.urls import reverse

from ...models import Beer, BeerUser, Drinks, BeerSpot, UserFollow, Notification, UserAchievementState, DrinkReaction, Brewery
from ..establishments.place_directory import TROPHY_URLS_CACHE_KEY
from ..messaging.notifications import save_notifications, send_notifications

TIER_NAMES = ["Bloqué", "Bronze", "Argent", "Or", "Platine"]
TIER_SLUGS = ["locked", "bronze", "silver", "gold", "platinum"]
TIER_XP_REWARDS = [0, 500, 1000, 1500, 2000]


class MemberCounts:
    """Valeurs que mesurent les trophées pour un membre, calculées à la demande et une seule fois (les dégustations en une requête)."""

    def __init__(self, user):
        self.user = user

    @cached_property
    def tastings(self):
        # Brasserie Ours doré : clé de comparaison (sans accents, ponctuation ni mots creux), « L'Ours-Doré » ou « Ours  doré » sont reconnus
        return Drinks.objects.filter(drinker=self.user).aggregate(
            total=Count('id'),
            bad=Count('id', filter=Q(note__lt=2)),
            guinness=Max('note', filter=Q(beer__name__icontains='guinness')),
            ours=Count('id', filter=Q(beer__brewery__match_key__contains='ours') & Q(beer__brewery__match_key__contains='dore')),
        )

    def added_beers(self):
        return Beer.objects.filter(added_by=self.user, is_deleted=False).count()

    def follows(self):
        return UserFollow.objects.filter(follower=self.user).count()

    def spots(self):
        return BeerSpot.objects.filter(user=self.user).count()

    def reactions(self):
        return DrinkReaction.objects.filter(user=self.user).count()

    def bio_mentions(self, word):
        return 1 if self.user.bio and word in self.user.bio.lower() else 0


@dataclass(frozen=True)
class Trophy:
    """Définition complète d'un trophée : ce qu'il mesure (`measure`, sur un MemberCounts) et ses paliers.

    `slug` : identifiant stable (la progression des membres, UserAchievementState et Notification, est rangée par identifiant).
    `points_per_unit` : points d'expérience gagnés par unité comptée (en plus des points des paliers)."""
    slug: str
    name: str
    description: str
    thresholds: tuple
    measure: Callable[[MemberCounts], int]
    category: str = "global"
    hidden: bool = False
    points_per_unit: int = 0


# Ajouter un trophée = une ligne ici (rien d'autre à modifier)
TROPHIES = (
    Trophy("poche", "Poche", "Ajouter des bières au catalogue", (1, 10, 100, 500), MemberCounts.added_beers, points_per_unit=100),
    Trophy("juge", "Juge", "Noter des bières", (5, 10, 100, 500), lambda c: c.tastings['total'], points_per_unit=100),
    Trophy("communaute", "Communautaire", "S'abonner à d'autres membres", (10, 100, 500, 1000), MemberCounts.follows),
    Trophy("voyageur", "Voyageur", "Placer des lieux sur la carte", (5, 50, 250, 500), MemberCounts.spots, points_per_unit=200),
    Trophy("bad_trip", "Mauvaise cuite", "Noter des bières en dessous de 2/10", (5, 50, 250, 500), lambda c: c.tastings['bad']),
    Trophy("cesar", "César", "Ajouter des pouces pour réagir aux avis", (10, 50, 100, 500), MemberCounts.reactions, points_per_unit=50),
    Trophy("irlandais", "Irlandais", "Noter une Guinness avec une excellente note", (5, 6, 8, 10), lambda c: c.tastings['guinness'] or 0, hidden=True),
    Trophy("picon", "Copain de Gaétan", "Mentionner le Picon dans sa biographie", (1, 1, 1, 1), lambda c: c.bio_mentions('picon'), hidden=True),
    Trophy("ours", "Ours doré", "Boire une bière de la brasserie de l'Ours Doré", (1, 1, 1, 1), lambda c: 1 if c.tastings['ours'] else 0,
           category="brewery"),
)

# Nom affiché de chaque trophée, par identifiant stable
ACHIEVEMENT_NAMES = {trophy.slug: trophy.name for trophy in TROPHIES}

TROPHY_URLS_CACHE_SECONDS = 3600


def _trophy_urls():
    """Page liée à un trophée, quand il y en a une (la fiche de la brasserie de l'Ours Doré). Gardée en cache : elle change rarement."""
    def compute():
        ours = Brewery.objects.filter(match_key__contains='ours').filter(match_key__contains='dore').order_by('id').only('slug').first()
        return {"ours": reverse('brewery_detail', args=[ours.slug])} if ours else {}
    return cache.get_or_set(TROPHY_URLS_CACHE_KEY, compute, TROPHY_URLS_CACHE_SECONDS)


def _build_achievement(trophy, current_val, url=None):
    thresholds = trophy.thresholds
    tier = 0
    for i, t in enumerate(thresholds):
        if current_val >= t:
            tier = i + 1

    if tier >= 4:
        tier = 4
        next_t = thresholds[-1]
        progress = 100
        current_display = next_t
    else:
        next_t = thresholds[tier]
        progress = int((current_val / next_t) * 100) if next_t > 0 else 0
        current_display = current_val

    display_desc = trophy.description
    if trophy.hidden and tier == 0:
        display_desc = "Défi caché... Explorez pour le découvrir !"

    return {
        'slug': trophy.slug,
        'name': trophy.name,
        'desc': display_desc,
        'category': trophy.category,
        'url': url,
        'current': current_display,
        'target': next_t,
        'progress': progress,
        'tier_name': TIER_NAMES[tier],
        'tier_level': tier,
        'tier_slug': TIER_SLUGS[tier],
        'is_maxed': tier == 4,
        'next_tier_xp': TIER_XP_REWARDS[tier + 1] if tier < 4 else 0,
    }


def _level(total_points):
    """Niveau atteint avec ce total de points : le premier coûte 600 points, chacun suivant 200 de plus."""
    level, required, remaining = 1, 600, total_points
    while remaining >= required:
        remaining -= required
        level += 1
        required += 200
    return {
        'total_points': total_points,
        'current_level': level,
        'points_in_current_level': remaining,
        'points_required_for_next_level': required,
        'progress_percentage': int((remaining / required) * 100),
    }


def get_user_achievements(user):
    """Calcule et retourne la liste des hauts faits d'un utilisateur, et son niveau."""
    counts = MemberCounts(user)
    values = {trophy.slug: trophy.measure(counts) for trophy in TROPHIES}
    urls = _trophy_urls()
    achievements = [_build_achievement(trophy, values[trophy.slug], urls.get(trophy.slug)) for trophy in TROPHIES]

    # Points des unités comptées, plus ceux des médailles débloquées
    total_points = sum(values[trophy.slug] * trophy.points_per_unit for trophy in TROPHIES)
    total_points += sum(TIER_XP_REWARDS[ach['tier_level']] for ach in achievements)
    return achievements, _level(total_points)


def check_and_notify_achievements(user):
    """Compare les paliers actuels à ceux déjà enregistrés, crée les notifications des paliers gagnés et retire celles des paliers perdus.

    Le compte du membre est verrouillé pendant le calcul ET la comparaison : deux appels simultanés (double clic, deux onglets) ne peuvent ni
    créer deux fois le même état, ni notifier deux fois le même palier, ni comparer des valeurs déjà dépassées. Les notifications sont
    diffusées une fois la transaction terminée."""
    if not user.is_authenticated:
        return
    with transaction.atomic():
        BeerUser.objects.select_for_update().get(pk=user.pk)  # verrou : un seul calcul à la fois pour ce membre
        achievements, _ = get_user_achievements(user)
        states = {state.achievement_slug: state for state in UserAchievementState.objects.filter(user=user)}
        new_states, changed_states, gained = [], [], []

        for ach in achievements:
            slug, level = ach['slug'], ach['tier_level']
            state = states.get(slug)
            if state is None:
                state = UserAchievementState(user=user, achievement_slug=slug, tier_level=0)
                new_states.append(state)
            if level > state.tier_level:
                gained.append(Notification(
                    recipient=user, notif_type='achievement', achievement_slug=slug, achievement_tier=level,
                    text_content=f"{ach['name']} ({ach['tier_name']})",
                ))
            elif level < state.tier_level:
                # Paliers perdus (ex. bière retirée) : leurs notifications disparaissent, en une requête
                Notification.objects.filter(recipient=user, notif_type='achievement', achievement_slug=slug, achievement_tier__gt=level).delete()
            if level != state.tier_level:
                state.tier_level = level
                if state.pk:
                    changed_states.append(state)

        UserAchievementState.objects.bulk_create(new_states)
        UserAchievementState.objects.bulk_update(changed_states, ['tier_level'])
        created = save_notifications(gained)

    if created:
        send_notifications(created)  # diffusion (appel réseau) hors transaction
