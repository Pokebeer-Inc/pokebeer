"""Fixtures partagées : isolation des services externes, utilisateurs et clients authentifiés."""
from unittest import mock

import pytest
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site
from django.core.files.storage import InMemoryStorage
from django.test import Client

from app.models import BeerUser
from tests import factories


def _network_disabled(*args, **kwargs):
    raise ConnectionError("Accès réseau interdit pendant les tests")


@pytest.fixture(autouse=True)
def isolated_services(settings, monkeypatch):
    """Aucun test ne doit joindre Gemini, Supabase, S3 ou Firebase, ni dépendre de secrets réels."""
    settings.GEMINI_API_KEY = "test-gemini-key"
    settings.SUPABASE_URL = None
    settings.SUPABASE_ANON_KEY = None
    settings.SUPABASE_SERVICE_ROLE_KEY = None
    settings.STORAGES = {**settings.STORAGES, "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"}}
    # Le champ garde le stockage résolu à l'import : on le remplace par un stockage mémoire (jamais le vrai bucket)
    monkeypatch.setattr(BeerUser._meta.get_field("avatar"), "storage", InMemoryStorage())
    monkeypatch.setattr("app.services.ai.config_client", _network_disabled)
    monkeypatch.setattr("app.views.api_views.config_client", _network_disabled)
    monkeypatch.setattr("app.services.realtime_service.requests.post", mock.Mock(side_effect=_network_disabled))
    monkeypatch.setattr("app.services.realtime_service.firebase_admin._apps", {})


@pytest.fixture(autouse=True)
def fast_settings(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    # Chaque Client de test recharge les middlewares : sans autorefresh, WhiteNoise rescanne tout STATIC_ROOT.
    settings.WHITENOISE_AUTOREFRESH = True
    # Le client de test parle en HTTP : la redirection HTTPS (production) le renverrait en boucle
    settings.SECURE_SSL_REDIRECT = False
    settings.PASSWORD_RESET_MIN_SECONDS = 0  # la temporisation anti-énumération n'a pas à ralentir la suite
    settings.PUBLIC_BASE_URL = 'https://pokebeer.test'


@pytest.fixture(autouse=True)
def geocoder(monkeypatch):
    """Remplace Nominatim : coordonnées fixes, appels inspectables via le mock retourné."""
    response = mock.Mock(status_code=200)
    response.json.return_value = [{"lat": "48.8566", "lon": "2.3522"}]
    get = mock.Mock(return_value=response)
    monkeypatch.setattr("app.models.mixins.requests.get", get)
    return get


@pytest.fixture
def google_app(db, settings):
    """Les pages login/register affichent le bouton Google, qui exige une SocialApp sur le site courant."""
    site, _ = Site.objects.update_or_create(pk=settings.SITE_ID, defaults={"domain": "testserver", "name": "test"})
    app = SocialApp.objects.create(provider="google", name="Google", client_id="test-client-id")
    app.sites.add(site)
    return app


@pytest.fixture
def user(db):
    return factories.make_user(username="alice")


@pytest.fixture
def other_user(db):
    return factories.make_user(username="bobby")


@pytest.fixture
def client_for(db):
    def _client_for(member):
        client = Client()
        client.force_login(member)
        return client
    return _client_for


@pytest.fixture
def auth_client(client_for, user):
    return client_for(user)


@pytest.fixture
def other_client(client_for, other_user):
    return client_for(other_user)


@pytest.fixture
def brewery(db):
    return factories.make_brewery(name="Brasserie Test")


@pytest.fixture
def beer(brewery, other_user):
    return factories.make_beer(name="Test IPA", brewery=brewery, added_by=other_user, style="IPA")
