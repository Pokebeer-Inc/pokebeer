"""En-têtes de sécurité, cookies et configuration de production."""
import pytest
from django.conf import settings as project_settings
from django.urls import reverse

from app.services import csp

pytestmark = pytest.mark.django_db


def header(response, name):
    return response.headers.get(name, "")


class TestPolicy:
    def test_site_pages_carry_the_csp(self, auth_client):
        policy = header(auth_client.get(reverse("index")), "Content-Security-Policy")
        assert "object-src 'none'" in policy and "frame-ancestors 'self'" in policy and "base-uri 'self'" in policy
        assert "form-action 'self'" in policy and "'unsafe-eval'" not in policy

    def test_google_login_form_may_redirect_to_google(self, client, google_app):
        """Le bouton Google poste un formulaire que le serveur redirige vers Google : `form-action` doit l'autoriser."""
        response = client.get(reverse("login"))
        html = response.content.decode()
        policy = header(response, "Content-Security-Policy")
        form_action = next(part for part in policy.split("; ") if part.startswith("form-action")).split()
        assert 'action="/accounts/google/login/"' in html
        assert "'self'" in form_action and "https://accounts.google.com" in form_action

    def test_form_actions_stay_restricted_to_the_site_and_google(self):
        form_action = next(part for part in csp.build_policy().split("; ") if part.startswith("form-action")).split()[1:]
        assert set(form_action) == {"'self'", "https://accounts.google.com"}

    def test_unknown_script_origins_are_not_allowed(self):
        script_src = next(part for part in csp.build_policy().split("; ") if part.startswith("script-src"))
        assert "*" not in script_src.split() and "http:" not in script_src
        assert set(csp.CDN_SCRIPTS) <= set(script_src.split())

    def test_realtime_origin_comes_from_the_supabase_setting(self):
        policy = csp.build_policy("https://abc.supabase.co")
        assert "https://abc.supabase.co" in policy and "wss://abc.supabase.co" in policy

    def test_no_realtime_origin_without_supabase(self):
        assert "supabase" not in csp.build_policy(None)

    def test_a_view_can_override_the_policy(self, rf):
        from django.http import HttpResponse
        from app.middleware import SecurityHeadersMiddleware
        response = SecurityHeadersMiddleware(lambda request: HttpResponse(headers={"Content-Security-Policy": "default-src 'none'"}))(rf.get("/"))
        assert response.headers["Content-Security-Policy"] == "default-src 'none'"

    def test_permissions_policy_and_framing(self, client, google_app):
        response = client.get(reverse("login"))
        assert "microphone=()" in header(response, "Permissions-Policy")
        assert header(response, "X-Frame-Options") == "SAMEORIGIN"
        assert header(response, "X-Content-Type-Options") == "nosniff"


class TestProductionSettings:
    def test_cookies_are_not_sent_cross_site_by_default(self):
        assert project_settings.SESSION_COOKIE_SAMESITE == project_settings.CSRF_COOKIE_SAMESITE == "Lax"
        assert project_settings.SESSION_COOKIE_SECURE and project_settings.CSRF_COOKIE_SECURE

    def test_no_wildcard_host_for_vercel(self):
        assert not any(host.startswith(".") and "vercel" in host for host in project_settings.ALLOWED_HOSTS)

    def test_https_is_enforced_outside_development(self):
        import importlib
        import os
        from unittest import mock

        import pokebeer.settings as module
        with mock.patch.dict(os.environ, {"DEBUG": "False", "DATABASE_URL": "sqlite://:memory:"}):
            with mock.patch("pokebeer.database.get_databases", return_value={}):
                reloaded = importlib.reload(module)
                assert reloaded.SECURE_SSL_REDIRECT and reloaded.SECURE_HSTS_SECONDS >= 31536000 and reloaded.SECURE_HSTS_INCLUDE_SUBDOMAINS
        importlib.reload(module)

    def test_third_party_scripts_are_pinned_with_integrity(self, client, google_app):
        html = client.get(reverse("login")).content.decode()
        for name in ("marked@", "dompurify@", "supabase-js@"):
            tag = next(line for line in html.splitlines() if name in line)
            assert 'integrity="sha384-' in tag and 'crossorigin="anonymous"' in tag
