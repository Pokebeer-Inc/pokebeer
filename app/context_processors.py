from django.conf import settings
from app.services.messaging.security import get_secure_channel_name

def supabase_config(request):
    """Expose les clés publiques Supabase à tous les templates HTML."""
    context = {
        'SUPABASE_URL': settings.SUPABASE_URL,
        'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
    }
    
    # Si l'utilisateur est connecté, on lui donne sa clé de canal privée
    if request.user.is_authenticated:
        context['WS_CHANNEL_NAME'] = get_secure_channel_name(request.user)
    return context


def chat_config(request):
    """Limite de longueur d'un message : le champ de saisie du chat et le serveur lisent la même valeur."""
    return {'CHAT_MESSAGE_MAX_LENGTH': settings.CHAT_MESSAGE_MAX_LENGTH}


# Barre de navigation du bas : (nom d'URL, libellé, noms d'URL qui la rendent « active », tracé de l'icône, bouton central, pastille de notifications).
# « Succès » et les réglages sont dans le Profil.
NAVIGATION = (
    ('index', 'Recherche', ('index', 'all_beers'), 'M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z', False, False),
    ('map', 'Carte', ('map',), 'M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l3.553 1.776A1 1 0 0021 17.882V7.118a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7', False, False),
    ('add_beer', 'Ajouter', ('add_beer',), 'M12 5v14m7-7H5', True, False),
    ('notebook', 'Carnet', ('notebook', 'notebook_detail', 'notebook_all'), 'M8 4h9a2 2 0 012 2v12a2 2 0 01-2 2H8a2 2 0 01-2-2V6a2 2 0 012-2zm0 0v16M4 8h2m-2 4h2m-2 4h2m6-8h4', False, False),
    ('account', 'Profil', ('account', 'account_settings', 'achievements'), 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z', False, True),
)


def main_nav(request):
    """Entrées de la barre de navigation, avec celle de la page courante marquée « active » : le gabarit n'a qu'une boucle à écrire."""
    current = getattr(request.resolver_match, 'url_name', None)
    return {'main_nav': [
        {'url_name': url_name, 'label': label, 'icon': icon, 'primary': primary, 'notification_dot': dot, 'active': current in active_names,
         'aria_label': "Ajouter une dégustation" if primary else label}
        for url_name, label, active_names, icon, primary, dot in NAVIGATION
    ]}
