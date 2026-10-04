"""Administration : limitation des tentatives de connexion, chemin configurable et CSP."""
import importlib

import pytest
from django.urls import clear_url_caches, reverse

from app.services.throttle import LOGIN_BY_IP
from tests import factories as f

pytestmark = pytest.mark.django_db

IP = {"REMOTE_ADDR": "198.51.100.10"}


class TestAdminLogin:
    url = "admin:login"

    def post(self, client, username, password="mauvais"):
        return client.post(reverse(self.url), {"username": username, "password": password, "next": reverse("admin:index")}, **IP)

    def test_admin_login_is_throttled(self, client, superuser):
        for index in range(LOGIN_BY_IP.attempts):
            self.post(client, f"ghost{index}")
        response = self.post(client, superuser.username, f.PASSWORD)
        assert response.status_code == 200 and "_auth_user_id" not in client.session

    def test_admin_login_still_works(self, client, superuser):
        assert self.post(client, superuser.username, f.PASSWORD).status_code == 302
        assert "_auth_user_id" in client.session


def test_admin_path_is_configurable(settings, client, superuser):
    settings.ADMIN_URL = "gestion-secrete/"
    import pokebeer.urls
    clear_url_caches()
    importlib.reload(pokebeer.urls)
    try:
        assert reverse("admin:login") == "/gestion-secrete/login/"
        assert client.get("/admin/login/").status_code == 404
    finally:
        settings.ADMIN_URL = "admin/"
        importlib.reload(pokebeer.urls)
        clear_url_caches()


def test_admin_alone_may_use_eval(client_for, superuser):
    assert "'unsafe-eval'" in client_for(superuser).get(reverse("admin:index")).headers["Content-Security-Policy"]
