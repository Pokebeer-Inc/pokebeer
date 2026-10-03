from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required

from ..models import Bar
from .place_views import (
    BAR, add_manager, edit_place, place_context, remove_manager, search_users_for_manager,
)


@login_required(login_url='login')
def bar_detail_view(request, bar_slug):
    """Affiche les détails d'un bar"""
    bar = get_object_or_404(Bar, slug=bar_slug)
    return render(request, 'bar_page.html', {'bar': bar, **place_context(bar, request.user)})


@login_required(login_url='login')
def edit_bar_view(request, bar_slug):
    """Permet aux managers de modifier les informations du bar."""
    return edit_place(request, BAR, bar_slug)


@login_required(login_url='login')
def add_bar_manager(request, bar_slug):
    """Ajoute un utilisateur comme collaborateur."""
    return add_manager(request, BAR, bar_slug)


@login_required(login_url='login')
def remove_bar_manager(request, bar_slug, username):
    """Retire l'accès à un collaborateur (sauf soi-même)."""
    return remove_manager(request, BAR, bar_slug, username)


@login_required(login_url='login')
def api_search_users_for_bar_manager(request, bar_slug):
    """Recherche AJAX de collaborateurs pour un bar."""
    return search_users_for_manager(request, BAR, bar_slug)
