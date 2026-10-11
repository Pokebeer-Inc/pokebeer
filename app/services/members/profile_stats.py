from django.db.models import Avg, Count
from django.utils import timezone
from datetime import timedelta

def get_user_statistics(user_drinks):
    """Calcule les statistiques utilisateur à partir d'un queryset de dégustations."""
    stats_drinks = user_drinks.filter(beer__is_deleted=False)
    
    last_month = timezone.now().date() - timedelta(days=30)
    
    averages = stats_drinks.aggregate(
        avg_note=Avg('note'),
        avg_abv=Avg('beer__degree'),
        avg_ibu=Avg('beer__bitterness')
    )

    loved_drinks = stats_drinks.filter(note__gte=7)
    
    pref_style_name = preferred_style(loved_drinks) or "Pas encore défini"

    return {
        'total_drinks': stats_drinks.count(),
        'drinks_last_month': stats_drinks.filter(date__gte=last_month).count(),
        'avg_note': averages['avg_note'] or 0,
        'avg_abv': averages['avg_abv'] or 0,
        'avg_ibu': averages['avg_ibu'] or 0,
        'pref_style': pref_style_name,
    }

def preferred_style(drinks):
    """Style le plus présent parmi ces dégustations (un champ peut en contenir plusieurs, séparés par des virgules), ou None.

    Le comptage est fait par la base (une ligne par style distinct), pas en parcourant chaque dégustation."""
    style_counts = {}
    rows = drinks.exclude(beer__style__isnull=True).exclude(beer__style='').values_list('beer__style').annotate(n=Count('id'))
    for style, count in rows:
        for name in [part.strip() for part in style.split(',') if part.strip()]:
            style_counts[name] = style_counts.get(name, 0) + count
    return max(style_counts, key=style_counts.get) if style_counts else None


def get_top_beers_data(user, user_drinks, include_empty=True):
    """Récupère et formate les données du top 3."""
    top_beers_data = []
    beers = [user.top_beer_1, user.top_beer_2, user.top_beer_3]
    # Les notes des (au plus) trois bières du top en une seule requête, sans parcourir toutes les dégustations
    notes = dict(user_drinks.filter(beer__in=[beer.id for beer in beers if beer]).values_list('beer', 'note'))

    for slot, beer in enumerate(beers, start=1):
        if beer:
            top_beers_data.append({
                'slot': slot,
                'beer': beer,
                'note': notes.get(beer.id)
            })
        elif include_empty:
            top_beers_data.append({
                'slot': slot,
                'beer': None,
                'note': None
            })
    return top_beers_data