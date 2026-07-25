from django.db.models import Avg, Count, Case, When, Value, IntegerField

def get_recommended_beers(user_drinks, unrated_beers):
    """Calcule et retourne les 5 meilleures recommandations de bières."""
    liked_drinks = user_drinks.filter(note__gte=7)
    
    if not liked_drinks.exists():
        return unrated_beers.annotate(
            global_rating=Avg('drinks__note')
        ).exclude(global_rating__isnull=True).order_by('-global_rating')[:5]

    pref_style = liked_drinks.exclude(beer_id__style__isnull=True).exclude(beer_id__style='').values('beer_id__style').annotate(c=Count('id')).order_by('-c').first()
    pref_style_name = pref_style['beer_id__style'] if pref_style else None
    
    pref_brewery = liked_drinks.values('beer_id__brewery_id').annotate(c=Count('id')).order_by('-c').first()
    pref_brewery_id = pref_brewery['beer_id__brewery_id'] if pref_brewery else None

    averages = liked_drinks.aggregate(
        avg_ibu=Avg('beer_id__bitterness'),
        avg_deg=Avg('beer_id__degree')
    )
    avg_ibu = float(averages['avg_ibu'] or 0)
    avg_deg = float(averages['avg_deg'] or 0)

    recommendations = unrated_beers.annotate(
        match_score=(
            Case(When(style=pref_style_name, then=Value(3)), default=Value(0), output_field=IntegerField()) +
            Case(When(brewery_id=pref_brewery_id, then=Value(2)), default=Value(0), output_field=IntegerField()) +
            Case(When(degree__range=(max(0, avg_deg - 1.5), avg_deg + 1.5), then=Value(1)), default=Value(0), output_field=IntegerField()) +
            Case(When(bitterness__range=(max(0, avg_ibu - 15), avg_ibu + 15), then=Value(1)), default=Value(0), output_field=IntegerField())
        )
    )
    
    recommended_beers = recommendations.filter(match_score__gt=0).annotate(
        global_rating=Avg('drinks__note')
    ).order_by('-match_score', '-global_rating')[:5]
    
    if not recommended_beers:
        recommended_beers = unrated_beers.annotate(
            global_rating=Avg('drinks__note')
        ).exclude(global_rating__isnull=True).order_by('-global_rating')[:5]
        
    return recommended_beers