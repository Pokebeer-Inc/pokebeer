"""Trophées des membres : calcul des paliers et notifications de progression."""
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count, Max, Q
from django.urls import reverse

from ...models import Beer, BeerUser, Drinks, BeerSpot, UserFollow, Notification, UserAchievementState, DrinkReaction, Brewery
from ..messaging.notifications import send_notifications

TIER_NAMES = ["Bloqué", "Bronze", "Argent", "Or", "Platine"]
TIER_SLUGS = ["locked", "bronze", "silver", "gold", "platinum"]
TIER_XP_REWARDS = [0, 500, 1000, 1500, 2000]

@dataclass(frozen=True)
class Trophy:
    """Définition d'un trophée : de quoi le reconnaître, jamais comment on compte (voir `_counters`).

    `points_per_unit` : points d'expérience gagnés par unité comptée (en plus des points des paliers)."""
    slug: str  # identifiant stable : la progression des membres (UserAchievementState, Notification) est rangée par identifiant, jamais par nom
    name: str
    description: str
    thresholds: tuple
    category: str = "global"
    hidden: bool = False
    points_per_unit: int = 0


# Ajouter un trophée = une ligne ici + son compteur dans `_counters`
TROPHIES = (
    Trophy("poche", "Poche", "Ajouter des bières au catalogue", (1, 10, 100, 500), points_per_unit=100),
    Trophy("juge", "Juge", "Noter des bières", (5, 10, 100, 500), points_per_unit=100),
    Trophy("communaute", "Communautaire", "S'abonner à d'autres membres", (10, 100, 500, 1000)),
    Trophy("voyageur", "Voyageur", "Placer des lieux sur la carte", (5, 50, 250, 500), points_per_unit=200),
    Trophy("bad_trip", "Mauvaise cuite", "Noter des bières en dessous de 2/10", (5, 50, 250, 500)),
    Trophy("cesar", "César", "Ajouter des pouces pour réagir aux avis", (10, 50, 100, 500), points_per_unit=50),
    Trophy("irlandais", "Irlandais", "Noter une Guinness avec une excellente note", (5, 6, 8, 10), hidden=True),
    Trophy("picon", "Copain de Gaétan", "Mentionner le Picon dans sa biographie", (1, 1, 1, 1), hidden=True),
    Trophy("ours", "Ours doré", "Boire une bière de la brasserie de l'Ours Doré", (1, 1, 1, 1), category="brewery"),
)

# Nom affiché de chaque trophée, par identifiant stable
ACHIEVEMENT_NAMES = {trophy.slug: trophy.name for trophy in TROPHIES}


def _counters(user):
    """Valeur actuelle de chaque trophée pour ce membre : {identifiant: nombre}. Un minimum de requêtes (les dégustations en une seule)."""
    # Brasserie Ours doré : clé de comparaison (sans accents, ponctuation ni mots creux), « L'Ours-Doré » ou « Ours  doré » sont reconnus comme « Ours Doré »
    tastings = Drinks.objects.filter(drinker=user).aggregate(
        total=Count('id'),
        bad=Count('id', filter=Q(note__lt=2)),
        guinness=Max('note', filter=Q(beer__name__icontains='guinness')),
        ours=Count('id', filter=Q(beer__brewery__match_key__contains='ours') & Q(beer__brewery__match_key__contains='dore')),
    )
    return {
        "poche": Beer.objects.filter(added_by=user, is_deleted=False).count(),
        "juge": tastings['total'],
        "communaute": UserFollow.objects.filter(follower=user).count(),
        "voyageur": BeerSpot.objects.filter(user=user).count(),
        "bad_trip": tastings['bad'],
        "cesar": DrinkReaction.objects.filter(user=user).count(),
        "irlandais": tastings['guinness'] or 0,
        "picon": 1 if user.bio and 'picon' in user.bio.lower() else 0,
        "ours": 1 if tastings['ours'] else 0,
    }


def _trophy_urls():
    """Page liée à un trophée, quand il y en a une (la fiche de la brasserie de l'Ours Doré)."""
    ours = Brewery.objects.filter(match_key__contains='ours').filter(match_key__contains='dore').order_by('id').first()
    return {"ours": reverse('brewery_detail', args=[ours.slug])} if ours else {}


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
    counters = _counters(user)
    urls = _trophy_urls()
    achievements = [_build_achievement(trophy, counters[trophy.slug], urls.get(trophy.slug)) for trophy in TROPHIES]

    # Points des unités comptées, plus ceux des médailles débloquées
    total_points = sum(counters[trophy.slug] * trophy.points_per_unit for trophy in TROPHIES)
    total_points += sum(TIER_XP_REWARDS[ach['tier_level']] for ach in achievements)
    return achievements, _level(total_points)


def check_and_notify_achievements(user):
    """Compare les paliers actuels à ceux déjà enregistrés, crée les notifications des paliers gagnés et retire celles des paliers perdus.

    Le compte du membre est verrouillé pendant la comparaison : deux appels simultanés (double clic, deux onglets) ne peuvent ni créer
    deux fois le même état, ni notifier deux fois le même palier. Les notifications sont diffusées une fois la transaction terminée."""
    if not user.is_authenticated: return
    achievements, _ = get_user_achievements(user)

    with transaction.atomic():
        BeerUser.objects.select_for_update().get(pk=user.pk)  # verrou : un seul calcul à la fois pour ce membre
        existing_states = {state.achievement_slug: state for state in UserAchievementState.objects.filter(user=user)}

        notifications_to_create = []
        states_to_update = []
        states_to_create = []

        for ach in achievements:
            state = existing_states.get(ach['slug'])

            if not state:
                # L'état n'existe pas encore
                state = UserAchievementState(user=user, achievement_slug=ach['slug'], tier_level=0)
                states_to_create.append(state)
                existing_states[ach['slug']] = state

            # Cas 1 : On passe à un niveau supérieur
            if ach['tier_level'] > state.tier_level and ach['tier_level'] > 0:
                notifications_to_create.append(
                    Notification(
                        recipient=user,
                        notif_type='achievement',
                        achievement_slug=ach['slug'],
                        text_content=f"{ach['name']} ({ach['tier_name']})"
                    )
                )

            # Cas 2 : On descend de niveau
            elif ach['tier_level'] < state.tier_level:
                # Nettoyage en 1 seule requête avec __in
                lost_tiers = [TIER_NAMES[t] for t in range(ach['tier_level'] + 1, state.tier_level + 1)]
                lost_texts = [f"{ach['name']} ({tier})" for tier in lost_tiers]
                Notification.objects.filter(
                    recipient=user,
                    notif_type='achievement',
                    achievement_slug=ach['slug'],
                    text_content__in=lost_texts
                ).delete()

            # Préparer la mise à jour
            if ach['tier_level'] != state.tier_level:
                state.tier_level = ach['tier_level']
                # On ajoute à states_to_update SEULEMENT si ce n'est pas un nouvel objet
                # (les nouveaux objets seront insérés avec le bon tier_level via bulk_create)
                if state.pk:
                    states_to_update.append(state)

        # Exécution des requêtes en base de données par lots
        if states_to_create:
            UserAchievementState.objects.bulk_create(states_to_create)
        if states_to_update:
            UserAchievementState.objects.bulk_update(states_to_update, ['tier_level'])
        created = Notification.objects.bulk_create(notifications_to_create) if notifications_to_create else []

    if created:
        # On pousse les trophées dans le WebSocket, hors transaction (appel réseau)
        send_notifications(created)
