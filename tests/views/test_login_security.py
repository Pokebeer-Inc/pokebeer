"""Brute-force, inscriptions en masse et chemins de connexion alternatifs."""
import pytest
from django.urls import reverse

from app.models import ThrottleHit
from app.services.throttle import LOGIN_BY_ACCOUNT, LOGIN_BY_IP, PRO_SIGNUP_BY_IP, SIGNUP_BY_IP
from tests import factories as f
from tests.helpers import messages_of

pytestmark = pytest.mark.django_db

LOGIN = "login"
IP = {"REMOTE_ADDR": "198.51.100.10"}


def attempt(client, username, password="mauvais", url=None, **extra):
    return client.post(url or reverse(LOGIN), {"username": username, "password": password}, **(extra or IP))


class TestSiteLogin:
    def test_ip_is_blocked_after_too_many_failures_even_with_the_right_password(self, client, google_app, user):
        for index in range(LOGIN_BY_IP.attempts):
            attempt(client, f"ghost{index}")
        response = attempt(client, user.username, f.PASSWORD)
        assert "_auth_user_id" not in client.session
        assert any("Trop de tentatives" in message for message in messages_of(response))

    def test_account_is_blocked_across_many_ips(self, client, google_app, user):
        for index in range(LOGIN_BY_ACCOUNT.attempts):
            attempt(client, user.username, REMOTE_ADDR=f"203.0.113.{index}")
        attempt(client, user.username, f.PASSWORD, REMOTE_ADDR="203.0.113.250")
        assert "_auth_user_id" not in client.session

    def test_a_blocked_attempt_does_not_check_the_password(self, client, google_app, user, monkeypatch):
        for index in range(LOGIN_BY_IP.attempts):
            attempt(client, f"ghost{index}")
        calls = []
        monkeypatch.setattr("app.models.BeerUser.check_password", lambda self, raw: calls.append(raw) or False)
        attempt(client, user.username, "guess")
        assert calls == []

    def test_other_visitors_are_unaffected(self, client, google_app, user):
        for index in range(LOGIN_BY_IP.attempts):
            attempt(client, f"ghost{index}")
        attempt(client, user.username, f.PASSWORD, REMOTE_ADDR="198.51.100.99")
        assert "_auth_user_id" in client.session

    def test_success_clears_the_account_counter(self, client, google_app, user):
        for _ in range(3):
            attempt(client, user.username)
        attempt(client, user.username, f.PASSWORD)
        assert not LOGIN_BY_ACCOUNT.exceeded(user.username)

    def test_suspended_account_attempts_are_counted_too(self, client, google_app):
        f.make_user(username="banned", is_active=False)
        attempt(client, "banned", f.PASSWORD)
        assert ThrottleHit.objects.filter(scope=LOGIN_BY_IP.scope).count() == 1


class TestAlternativeLoginPaths:
    def test_allauth_login_page_leads_to_ours(self, client):
        response = client.get("/accounts/login/", {"next": "/beers/"})
        assert response.status_code == 302 and response.url == f"{reverse(LOGIN)}?next=%2Fbeers%2F"

    def test_allauth_signup_page_leads_to_ours(self, client):
        assert client.get("/accounts/signup/").url == reverse("register")

    def test_protected_views_send_visitors_to_our_login(self, client):
        for url in (reverse("analyze_label"), reverse("api_update_fcm_token")):
            assert client.post(url).url.startswith(reverse(LOGIN))


class TestSignupThrottle:
    def test_registrations_are_limited_per_ip(self, client, google_app):
        for index in range(SIGNUP_BY_IP.attempts):
            client.post(reverse("register"), {"username": f"bot{index}"}, **IP)
        response = client.post(reverse("register"), {"username": "one-more"}, **IP)
        assert response.status_code == 429

    def test_pro_registrations_are_limited_per_ip(self, client, google_app):
        for _ in range(PRO_SIGNUP_BY_IP.attempts):
            client.post(reverse("register_pro", args=["bar"]), {}, **IP)
        assert client.post(reverse("register_pro", args=["bar"]), {}, **IP).status_code == 429

    def test_browsing_the_form_is_never_limited(self, client, google_app):
        for _ in range(SIGNUP_BY_IP.attempts + 2):
            assert client.get(reverse("register"), **IP).status_code == 200


class TestRedirectsAndAccess:
    EVIL = ["https://evil.example/", "//evil.example/", "javascript:alert(1)"]

    @pytest.mark.parametrize("referer", EVIL)
    def test_follow_never_redirects_to_a_foreign_referer(self, auth_client, other_user, referer):
        response = auth_client.post(reverse("follow_user", args=[other_user.username]), HTTP_REFERER=referer)
        assert response.url == reverse("index")

    @pytest.mark.parametrize("referer", EVIL)
    def test_remove_follower_never_redirects_to_a_foreign_referer(self, auth_client, other_user, referer):
        response = auth_client.post(reverse("remove_follower", args=[other_user.username]), HTTP_REFERER=referer)
        assert response.url == reverse("account")

    @pytest.mark.parametrize("referer", EVIL)
    def test_rating_never_redirects_to_a_foreign_referer(self, auth_client, beer, referer):
        response = auth_client.post(reverse("rate_beer", args=[beer.slug]), {"date": "2026-01-01", "note": 5}, HTTP_REFERER=referer)
        assert response.url == reverse("index")

    @pytest.mark.parametrize("referer", EVIL)
    def test_deleting_a_tasting_never_redirects_to_a_foreign_referer(self, auth_client, user, beer, referer):
        drink = f.make_drink(user, beer)
        response = auth_client.post(reverse("delete_drink", args=[drink.slug]), HTTP_REFERER=referer)
        assert response.url == reverse("account")

    def test_a_page_of_this_site_is_still_honoured(self, auth_client, other_user):
        response = auth_client.post(reverse("follow_user", args=[other_user.username]), HTTP_REFERER="http://testserver/beers/")
        assert response.url == "http://testserver/beers/"

    @pytest.mark.parametrize("name", ["search_beer", "search_brewery"])
    def test_catalogue_search_requires_login(self, client, name):
        response = client.get(reverse(name), {"term": "ab"})
        assert response.status_code == 302 and response.url.startswith(reverse(LOGIN))

    @pytest.mark.parametrize("name", ["search_beer", "search_brewery"])
    def test_catalogue_search_works_when_logged_in(self, auth_client, name):
        assert auth_client.get(reverse(name), {"term": "ab"}).status_code == 200

    def test_no_route_sends_visitors_to_the_allauth_login_page(self, client, google_app):
        from django.urls import URLPattern, get_resolver
        fixed = [p.name for p in get_resolver("app.urls").url_patterns if isinstance(p, URLPattern) and p.name and "<" not in str(p.pattern)]
        skipped = {"cron_purge_inactive_accounts"}
        for name in set(fixed) - skipped:
            response = client.get(reverse(name))
            assert not response.headers.get("Location", "").startswith("/accounts/login/"), name


class TestGoogleLogin:
    def test_login_pages_offer_google_through_a_post_form(self, client, google_app):
        for name in ("login", "register"):
            html = client.get(reverse(name)).content.decode()
            assert '<form method="post" action="/accounts/google/login/"' in html and "csrfmiddlewaretoken" in html

    def test_a_link_cannot_start_the_google_flow(self, client, google_app):
        response = client.get("/accounts/google/login/")
        assert response.status_code == 200  # page de confirmation : aucune redirection vers Google
