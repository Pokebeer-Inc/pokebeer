from django.db.models import Avg, Count
from django.utils import timezone
from datetime import timedelta

def get_user_statistics(user_drinks):
    """Calcule les statistiques utilisateur à partir d'un queryset de dégustations."""
    stats_drinks = user_drinks.filter(beer_id__is_deleted=False)
    
    last_month = timezone.now().date() - timedelta(days=30)
    
    averages = stats_drinks.aggregate(
        avg_note=Avg('note'),
        avg_abv=Avg('beer_id__degree'),
        avg_ibu=Avg('beer_id__bitterness')
    )

    loved_drinks = stats_drinks.filter(note__gte=7)
    pref_style = loved_drinks.exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values('beer_id__style').annotate(c=Count('id')).order_by('-c').first()

    return {
        'total_drinks': stats_drinks.count(),
        'drinks_last_month': stats_drinks.filter(date__gte=last_month).count(),
        'avg_note': averages['avg_note'] or 0,
        'avg_abv': averages['avg_abv'] or 0,
        'avg_ibu': averages['avg_ibu'] or 0,
        'pref_style': pref_style['beer_id__style'] if pref_style else "Pas encore défini",
    }

def get_top_beers_data(user, user_drinks, include_empty=True):
    """Récupère et formate les données du top 3."""
    top_beers_data = []
    beers = [user.top_beer_1, user.top_beer_2, user.top_beer_3]
    
    for slot, beer in enumerate(beers, start=1):
        if beer:
            drink = next((d for d in user_drinks if d.beer_id_id == beer.id), None)
            top_beers_data.append({
                'slot': slot,
                'beer': beer,
                'note': drink.note if drink else None
            })
        elif include_empty:
            top_beers_data.append({
                'slot': slot,
                'beer': None,
                'note': None
            })
    return top_beers_data