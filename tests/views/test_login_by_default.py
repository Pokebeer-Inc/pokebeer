"""Connexion exigée par défaut : toute route du site renvoie un visiteur anonyme vers la connexion, sauf la liste publique ci-dessous."""
import re

import pytest
from django.conf import settings
from django.urls import URLResolver, get_resolver, reverse

pytestmark = pytest.mark.django_db

# Pages volontairement ouvertes sans connexion (chacune porte @login_not_required dans le code)
PUBLIC = {
    'login', 'register', 'register_pro', 'password_reset', 'password_reset_done', 'password_reset_confirm', 'password_reset_complete',
    'email_preferences', 'email_unsubscribe', 'assetlinks', 'privacy_policy', 'cron_purge_inactive_accounts', 'postal_code_lookup',
    'allauth_login_redirect', 'allauth_signup_redirect', 'allauth_reset_redirect', 'allauth_password_change_redirect',
    'allauth_password_set_redirect',
}


def site_routes(patterns=None, prefix=''):
    """(nom, chemin d'exemple) de chaque route du site hors administration et hors allauth (protégés par leurs propres règles)."""
    for pattern in get_resolver().url_patterns if patterns is None else patterns:
        route = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            yield from site_routes(pattern.url_patterns, route)
        elif not route.startswith((settings.ADMIN_URL, '__reload__', settings.MEDIA_URL.strip('/'))) and pattern.name:
            route = re.sub(r'<int:[^>]+>', '1', route)
            yield pattern.name, '/' + re.sub(r'<[^>]+>', 'x', route).replace('^', '').replace('$', '')


PRIVATE = sorted({(name, path) for name, path in site_routes() if name not in PUBLIC and not path.startswith('/accounts/')})


@pytest.mark.parametrize("name, path", PRIVATE, ids=[name for name, _ in PRIVATE])
@pytest.mark.parametrize("method", ["get", "post"])
def test_anonymous_visitors_are_sent_to_the_login_page(client, name, path, method):
    response = getattr(client, method)(path)
    assert response.status_code == 302 and response.url.startswith(reverse('login') + '?next=')


@pytest.mark.parametrize("name", sorted(PUBLIC))
def test_public_pages_are_declared_as_such(name):
    callbacks = {pattern.name: pattern.callback for _, pattern in _patterns(get_resolver().url_patterns)}
    assert getattr(callbacks[name], 'login_required', True) is False


def _patterns(patterns, prefix=''):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _patterns(pattern.url_patterns, prefix + str(pattern.pattern))
        else:
            yield prefix + str(pattern.pattern), pattern


def test_the_middleware_is_installed():
    assert 'app.middleware.LoginRequiredMiddleware' in settings.MIDDLEWARE
