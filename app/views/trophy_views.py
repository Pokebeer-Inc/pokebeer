from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .utils import get_user_achievements

@login_required(login_url='login')
def achievements_view(request):
    """Page des trophées, hauts faits et cosmétiques."""
    achievements = get_user_achievements(request.user)
    return render(request, 'achievements.html', {'achievements': achievements})