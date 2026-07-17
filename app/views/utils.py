from django.db.models import Max
from ..models import UserBlock, Beer, Drinks, BeerSpot, UserFollow, Notification, UserAchievementState

def get_excluded_users(user):
    """Retourne la liste des IDs d'utilisateurs avec qui il y a un blocage."""
    if not user.is_authenticated: return []
    blocked_by_me = UserBlock.objects.filter(blocker=user).values_list('blocked_id', flat=True)
    blocking_me = UserBlock.objects.filter(blocked=user).values_list('blocker_id', flat=True)
    return list(set(blocked_by_me) | set(blocking_me))

def get_user_achievements(user):
    """Calcule et retourne la liste des hauts faits d'un utilisateur."""
    # --- 1. Récupération des statistiques réelles du joueur ---
    poche_count = Beer.objects.filter(added_by=user).count()
    juge_count = Drinks.objects.filter(drinker_id=user).count()
    comm_count = UserFollow.objects.filter(follower=user).count()
    voyageur_count = BeerSpot.objects.filter(user=user).count()
    bad_count = Drinks.objects.filter(drinker_id=user, note__lt=2).count()
    
    guinness_drink = Drinks.objects.filter(drinker_id=user, beer_id__name__icontains='guinness').aggregate(Max('note'))
    irlandais_score = guinness_drink['note__max'] or 0
    
    has_picon = 1 if user.bio and 'picon' in user.bio.lower() else 0
    has_ours = 1 if Drinks.objects.filter(drinker_id=user, beer_id__brewery_id__name__icontains='ours dor').exists() else 0

    # --- 2. Fonction utilitaire pour générer un trophée ---
    def build_achievement(name, current_val, thresholds, icon_svg, desc, is_hidden=False):
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

        colors = {
            0: {
                'bg': 'bg-base-200', 'border': 'border-base-300', 
                'text_icon': 'text-gray-400', 'text_title': 'text-gray-800', 'text_desc': 'text-gray-500', 
                'bar': 'progress-neutral', 'badge': '', 'extra_classes': ''
            },
            1: {
                'bg': 'bg-gradient-to-br from-[#CD7F32] to-[#8C5722]', 
                'border': 'border-[#CD7F32]/50', 
                'text_icon': 'text-[#CD7F32]', 'text_title': 'text-white', 'text_desc': 'text-white/80', 
                'bar': '[&::-webkit-progress-value]:bg-white [&::-moz-progress-bar]:bg-white', 
                'badge': 'bg-white text-[#CD7F32] border-none shadow-sm', 'extra_classes': 'shine-effect'
            },
            2: {
                'bg': 'bg-gradient-to-br from-[#F8F8F8] to-[#C0C0C0]', 
                'border': 'border-[#C0C0C0]/50', 
                'text_icon': 'text-gray-600', 'text_title': 'text-gray-900', 'text_desc': 'text-gray-700', 
                'bar': '[&::-webkit-progress-value]:bg-gray-800 [&::-moz-progress-bar]:bg-gray-800', 
                'badge': 'bg-gray-800 text-[#C0C0C0] border-none shadow-sm', 'extra_classes': 'shine-effect'
            },
            3: {
                'bg': 'bg-gradient-to-br from-[#FFF080] to-[#FFD700]', 
                'border': 'border-[#FFD700]/50', 
                'text_icon': 'text-[#D4AF37]', 'text_title': 'text-gray-900', 'text_desc': 'text-yellow-900', 
                'bar': '[&::-webkit-progress-value]:bg-gray-900 [&::-moz-progress-bar]:bg-gray-900', 
                'badge': 'bg-gray-900 text-[#FFD700] border-none shadow-sm', 'extra_classes': 'shine-effect'
            },
            4: {
                'bg': 'bg-gradient-to-br from-[#FFFFFF] to-[#E5E4E2]', 
                'border': 'border-[#E5E4E2]/50', 
                'text_icon': 'text-gray-500', 'text_title': 'text-gray-900', 'text_desc': 'text-gray-600', 
                'bar': '[&::-webkit-progress-value]:bg-indigo-900 [&::-moz-progress-bar]:bg-indigo-900', 
                'badge': 'bg-indigo-900 text-[#E5E4E2] border-none shadow-sm', 'extra_classes': 'shine-effect'
            }
        }
        
        tier_names = ["Bloqué", "Bronze", "Argent", "Or", "Platine"]
        
        display_desc = desc
        if is_hidden and tier == 0:
            display_desc = "Défi caché... Explorez pour le découvrir !"

        return {
            'name': name,
            'desc': display_desc,
            'icon': icon_svg,
            'current': current_display,
            'target': next_t,
            'progress': progress,
            'tier_name': tier_names[tier],
            'tier_level': tier, # Ajouté pour faciliter le filtrage
            'style': colors[tier],
            'is_maxed': tier == 4
        }

    # --- 3. Définition des icônes SVG ---
    icon_barrel = '<g transform="scale(0.046875)" fill="currentColor" stroke="none"><path d="M410.613,5.068C409.354,2.002,406.368,0,403.055,0H108.927c-3.314,0-6.3,2.002-7.558,5.068 C85.275,44.276,72.907,85.096,64.611,126.39c-0.889,4.425,3.064,8.843,7.488,9.733l114.692,0.047 c-5.371,83.308-5.778,163.839-1.214,239.66H79.419c-13.364-70.389-14.971-142.725-4.415-213.951 c0.661-4.464-2.421-8.618-6.884-9.28c-4.472-0.67-8.619,2.421-9.28,6.884c-17.371,117.208-2.665,237.355,42.529,347.449 c1.258,3.065,4.244,5.068,7.558,5.068h294.128c3.314,0,6.3-2.002,7.558-5.068c32.296-78.678,48.99-161.558,49.615-246.335 C460.876,172.822,444.183,86.848,410.613,5.068z M413.259,59.915c2.901,9.039,5.59,18.12,8.082,27.234H322.7 c-0.842-9.203-1.755-18.311-2.739-27.234H413.259z M114.43,16.34h283.122c3.619,9.029,7.018,18.11,10.215,27.234H104.222 C107.423,34.423,110.825,25.34,114.43,16.34z M306.293,87.149h-99.399c0.797-9.133,1.65-18.236,2.547-27.234h94.075 C304.512,68.831,305.441,77.933,306.293,87.149z M98.756,59.915h94.262c-0.89,9.003-1.733,18.108-2.525,27.234H90.681 C93.17,78.021,95.866,68.939,98.756,59.915z M82.685,119.83c1.186-5.458,2.445-10.906,3.775-16.34h339.124 c1.334,5.437,2.604,10.883,3.794,16.34H82.685z M98.777,452.085c-2.887-9.029-5.591-18.106-8.073-27.234h98.577 c0.842,9.201,1.755,18.309,2.739,27.234H98.777z M397.552,495.66H114.43c-3.61-9.011-6.996-18.095-10.189-27.234h96.89 c0.041,0,108.787,0,108.787,0c0.042,0,97.849,0,97.849,0C404.57,477.55,401.171,486.631,397.552,495.66z M205.687,424.851h99.399 c-0.799,9.136-1.651,18.24-2.547,27.234h-94.076C207.47,443.167,206.54,434.065,205.687,424.851z M413.259,452.085h-94.297 c0.89-8.999,1.733-18.105,2.525-27.234h99.854C418.849,433.965,416.161,443.046,413.259,452.085z M425.584,408.511H313.879 c-0.023,0-0.046,0-0.068,0H196.894c-0.039,0-110.384,0-110.384,0c-1.326-5.434-2.589-10.879-3.773-16.34h346.641 C428.187,397.628,426.919,403.074,425.584,408.511z M432.715,375.83H325.196c2.197-34.122,3.586-68.228,4.112-101.515 c0.071-4.512-3.528-8.227-8.041-8.298c-0.044-0.001-0.087-0.001-0.131-0.001c-4.452,0-8.097,3.573-8.167,8.042 c-0.527,33.365-1.929,67.563-4.149,101.773H201.949c-4.607-75.751-4.198-156.292,1.217-239.66h106.871 c2.067,34.02,3.143,69.404,3.179,105.343c0.004,4.51,3.661,8.161,8.17,8.161c4.52-0.004,8.175-3.666,8.17-8.179 c-0.035-35.913-1.102-71.289-3.147-105.327h106.308C447.866,215.454,447.866,296.546,432.715,375.83z"/><path d="M72.139,136.127C72.177,136.131,72.165,136.13,72.139,136.127L72.139,136.127z"/><path d="M72.139,136.127c-0.011-0.001-0.016-0.002-0.04-0.004C72.099,136.123,72.119,136.125,72.139,136.127z"/><path d="M72.099,136.123C71.748,136.099,72.454,136.194,72.099,136.123L72.099,136.123z"/><circle cx="139.351" cy="310.468" r="8.17"/><circle cx="106.67" cy="343.149" r="8.17"/><circle cx="405.318" cy="168.851" r="8.17"/></g>'
    icon_star = '<path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />'
    icon_users = '<path stroke-linecap="round" stroke-linejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />'
    icon_map = '<path stroke-linecap="round" stroke-linejoin="round" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />'
    icon_skull = '<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />'
    icon_magic = '<path stroke-linecap="round" stroke-linejoin="round" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />'
    icon_heart = '<path stroke-linecap="round" stroke-linejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" />'
    icon_ours_dore = '<g transform="translate(2, 0) scale(0.1188)"><g transform="translate(0, 202) scale(0.1, -0.1)" fill="currentColor" stroke="none"><path d="M655 1894 c-53 -54 -87 -116 -109 -201 -16 -61 -21 -123 -10 -123 3 0 19 9 35 21 16 11 50 24 74 27 l45 7 4 110 c2 61 11 131 19 158 20 62 4 63 -58 1z"/><path d="M955 1873 c19 -69 24 -115 25 -203 l0 -96 36 4 c21 3 52 -3 75 -13 21 -10 42 -15 46 -12 14 14 -20 144 -54 209 -51 97 -146 180 -128 111z"/><path d="M332 1686 c-73 -68 -142 -213 -142 -298 0 -33 1 -33 42 -12 17 9 49 17 72 19 l41 3 -3 54 c-4 59 11 157 35 226 8 24 12 46 9 49 -2 3 -27 -16 -54 -41z"/><path d="M1280 1673 c0 -5 10 -33 21 -63 15 -37 23 -87 27 -152 l5 -98 34 0 c18 0 52 -9 74 -21 23 -11 44 -18 47 -15 10 11 -17 129 -43 182 -14 28 -40 70 -58 93 -43 54 -107 98 -107 74z"/><path d="M584 1541 c-74 -45 -108 -130 -103 -254 7 -141 73 -242 159 -242 51 0 87 28 125 96 28 51 30 60 30 164 0 99 -3 116 -26 160 -44 86 -118 117 -185 76z"/><path d="M969 1507 c-20 -13 -46 -45 -61 -76 -23 -45 -28 -67 -28 -131 0 -93 19 -154 66 -208 44 -52 90 -68 136 -49 142 59 173 324 51 439 -55 52 -111 61 -164 25z"/><path d="M244 1326 c-36 -16 -85 -82 -104 -141 -8 -22 -14 -76 -14 -121 0 -70 4 -89 30 -140 37 -76 82 -108 141 -101 57 6 97 38 129 103 24 49 26 63 21 127 -9 112 -42 205 -89 250 -42 40 -65 44 -114 23z"/><path d="M1375 1302 c-51 -10 -95 -80 -121 -193 -41 -181 31 -324 163 -324 44 0 56 5 82 29 70 67 94 235 50 352 -35 94 -106 149 -174 136z"/><path d="M755 996 c-84 -20 -145 -56 -225 -131 -41 -39 -105 -92 -141 -118 -143 -100 -193 -190 -193 -347 0 -121 25 -189 95 -261 72 -74 141 -102 254 -103 52 0 107 6 130 14 64 22 242 18 357 -8 114 -26 154 -27 226 -8 166 45 247 163 247 361 0 87 -3 107 -26 156 -36 75 -85 128 -172 183 -41 25 -99 75 -133 114 -69 76 -143 121 -240 146 -72 19 -110 19 -179 2z m245 -141 c0 -3 -16 -25 -35 -50 -37 -50 -59 -111 -70 -199 l-7 -56 61 0 c72 0 148 26 202 70 44 35 48 36 44 13 -2 -10 -4 -78 -4 -152 l-1 -133 -39 35 c-50 45 -136 77 -208 77 l-56 0 7 -64 c8 -83 28 -137 71 -197 l35 -49 -150 0 -150 0 35 51 c40 58 64 130 67 204 l3 50 -53 3 c-70 4 -140 -20 -202 -69 l-50 -39 0 155 c0 85 2 155 4 155 2 0 20 -15 40 -34 47 -45 131 -76 206 -76 67 0 65 -5 49 90 -13 81 -41 146 -81 188 l-32 32 157 0 c86 0 157 -2 157 -5z"/></g></g>'

    # --- 4. Construction de la liste finale ---
    return [
        build_achievement("Poche", poche_count, [1, 10, 100, 500], icon_barrel, "Ajouter des bières au catalogue"),
        build_achievement("Juge", juge_count, [5, 10, 100, 500], icon_star, "Noter des bières"),
        build_achievement("Communautaire", comm_count, [10, 100, 500, 1000], icon_users, "S'abonner à d'autres membres"),
        build_achievement("Voyageur", voyageur_count, [5, 50, 250, 500], icon_map, "Placer des lieux sur la carte"),
        build_achievement("Mauvaise cuite", bad_count, [5, 50, 250, 500], icon_skull, "Noter des bières en dessous de 2/10"),
        build_achievement("Irlandais", irlandais_score, [5, 6, 8, 10], icon_magic, "Noter une Guinness avec une excellente note", is_hidden=True),
        build_achievement("Copain de Gaétan", has_picon, [1, 1, 1, 1], icon_heart, "Mentionner le Picon dans sa biographie", is_hidden=True),
        build_achievement("Ours doré", has_ours, [1, 1, 1, 1], icon_ours_dore, "Boire une bière de la brasserie Ours Doré", is_hidden=True),
    ]
    
def check_and_notify_achievements(user):
    if not user.is_authenticated: return
    achievements = get_user_achievements(user)
    
    for ach in achievements:
        state, created = UserAchievementState.objects.get_or_create(
            user=user, achievement_name=ach['name']
        )
        # Si on passe à un niveau supérieur (et que ce n'est pas le niveau 0 bloqué)
        if ach['tier_level'] > state.tier_level and ach['tier_level'] > 0:
            Notification.objects.create(
                recipient=user,
                notif_type='achievement',
                achievement_name=ach['name'],
                text_content=f"{ach['name']} ({ach['tier_name']})"
            )
        # On met à jour l'état en base
        if ach['tier_level'] != state.tier_level:
            state.tier_level = ach['tier_level']
            state.save()