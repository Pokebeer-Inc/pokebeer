from django.db.models import Max

from ..models import Beer, Drinks, UserBlock, BeerSpot, UserFollow, Notification, UserAchievementState, DrinkReaction
from ..services.realtime_service import broadcast_notifications

TIER_NAMES = ["Bloqué", "Bronze", "Argent", "Or", "Platine"]
TIER_SLUGS = ["locked", "bronze", "silver", "gold", "platinum"]

def get_excluded_users(user):
    """Retourne la liste des IDs d'utilisateurs avec qui il y a un blocage."""
    if not user.is_authenticated: return []
    blocked_by_me = UserBlock.objects.filter(blocker=user).values_list('blocked_id', flat=True)
    blocking_me = UserBlock.objects.filter(blocked=user).values_list('blocker_id', flat=True)
    return list(set(blocked_by_me) | set(blocking_me))

def get_user_achievements(user):
    """Calcule et retourne la liste des hauts faits d'un utilisateur."""
    poche_count = Beer.objects.filter(added_by=user).count()
    juge_count = Drinks.objects.filter(drinker_id=user).count()
    comm_count = UserFollow.objects.filter(follower=user).count()
    voyageur_count = BeerSpot.objects.filter(user=user).count()
    bad_count = Drinks.objects.filter(drinker_id=user, note__lt=2).count()
    cesar_count = DrinkReaction.objects.filter(user=user).count()
    
    guinness_drink = Drinks.objects.filter(drinker_id=user, beer_id__name__icontains='guinness').aggregate(Max('note'))
    irlandais_score = guinness_drink['note__max'] or 0
    
    has_picon = 1 if user.bio and 'picon' in user.bio.lower() else 0
    has_ours = 1 if Drinks.objects.filter(drinker_id=user, beer_id__brewery_id__name__icontains='ours dor').exists() else 0

    def build_achievement(slug, name, current_val, thresholds, desc, is_hidden=False):
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

        display_desc = desc
        if is_hidden and tier == 0:
            display_desc = "Défi caché... Explorez pour le découvrir !"

        return {
            'slug': slug,
            'name': name,
            'desc': display_desc,
            'current': current_display,
            'target': next_t,
            'progress': progress,
            'tier_name': TIER_NAMES[tier],
            'tier_level': tier,
            'tier_slug': TIER_SLUGS[tier],
            'is_maxed': tier == 4
        }

    return [
        build_achievement("poche", "Poche", poche_count, [1, 10, 100, 500], "Ajouter des bières au catalogue"),
        build_achievement("juge", "Juge", juge_count, [5, 10, 100, 500], "Noter des bières"),
        build_achievement("communaute", "Communautaire", comm_count, [10, 100, 500, 1000], "S'abonner à d'autres membres"),
        build_achievement("voyageur", "Voyageur", voyageur_count, [5, 50, 250, 500], "Placer des lieux sur la carte"),
        build_achievement("bad_trip", "Mauvaise cuite", bad_count, [5, 50, 250, 500], "Noter des bières en dessous de 2/10"),
        build_achievement("cesar", "César", cesar_count, [10, 50, 100, 500], "Ajouter des pouces pour réagir aux avis"),
        build_achievement("irlandais", "Irlandais", irlandais_score, [5, 6, 8, 10], "Noter une Guinness avec une excellente note", is_hidden=True),
        build_achievement("picon", "Copain de Gaétan", has_picon, [1, 1, 1, 1], "Mentionner le Picon dans sa biographie", is_hidden=True),
        build_achievement("ours", "Ours doré", has_ours, [1, 1, 1, 1], "Boire une bière de la brasserie Ours Doré", is_hidden=True),
    ]
    
def check_and_notify_achievements(user):
    if not user.is_authenticated: return
    achievements = get_user_achievements(user)
    
    # Récupération de tous les états existants en 1 seule requête
    existing_states = {state.achievement_name: state for state in UserAchievementState.objects.filter(user=user)}
    
    notifications_to_create = []
    states_to_update = []
    states_to_create = []
    
    for ach in achievements:
        state = existing_states.get(ach['name'])
        
        if not state:
            # L'état n'existe pas encore
            state = UserAchievementState(user=user, achievement_name=ach['name'], tier_level=0)
            states_to_create.append(state)
            existing_states[ach['name']] = state
        
        # Cas 1 : On passe à un niveau supérieur
        if ach['tier_level'] > state.tier_level and ach['tier_level'] > 0:
            notifications_to_create.append(
                Notification(
                    recipient=user,
                    notif_type='achievement',
                    achievement_name=ach['name'],
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
                achievement_name=ach['name'],
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
    if notifications_to_create:
        created_notifs = Notification.objects.bulk_create(notifications_to_create)
        
        # On pousse les trophées dans le WebSocket
        broadcast_notifications(created_notifs)
