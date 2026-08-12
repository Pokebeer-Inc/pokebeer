from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required

from ..models import Bar
@login_required(login_url='login')
def bar_detail_view(request, bar_id):
    """Affiche les détails d'un bar"""
    bar = get_object_or_404(Bar, id=bar_id)

    context = {
        'bar': bar,
    }
    return render(request, 'bar_page.html', context)