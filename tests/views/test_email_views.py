"""Choix des e-mails promotionnels (lien signé, compte) et App Links Android."""
import pytest
from django.test import Client
from django.urls import reverse

from app.models import BeerUser
from app.services import marketing
from tests import factories as f

pytestmark = pytest.mark.django_db


def token_of(member):
    return marketing.preferences_url(member).rstrip("/").rsplit("/", 1)[1]


def prefs(token):
    return reverse("email_preferences", args=[token])


def consent(member):
    return BeerUser.objects.get(pk=member.pk).marketing_opt_in


class TestPreferencesPage:
    def test_anonymous_visitor_with_the_link_can_unsubscribe(self, client, user):
        response = client.post(prefs(token_of(user)), {"choice": "refuse"})
        assert response.status_code == 200 and not consent(user)
        assert BeerUser.objects.get(pk=user.pk).marketing_consent_source == "email_link"

    def test_and_come_back(self, client, user):
        marketing.set_consent(user, False, "account")
        client.post(prefs(token_of(user)), {"choice": "accept"})
        assert consent(user)

    def test_get_changes_nothing(self, client, user):
        assert client.get(prefs(token_of(user))).status_code == 200 and consent(user)

    def test_unknown_choice_is_rejected(self, client, user):
        assert client.post(prefs(token_of(user)), {"choice": "maybe"}).status_code == 400

    def test_forged_token_gives_a_404_on_every_method(self, client, user):
        forged = token_of(user)[:-3] + "abc"
        assert client.get(prefs(forged)).status_code == 404
        assert client.post(prefs(forged), {"choice": "refuse"}).status_code == 404 and consent(user)

    def test_the_form_is_protected_by_csrf(self, user):
        strict = Client(enforce_csrf_checks=True)
        assert strict.post(prefs(token_of(user)), {"choice": "refuse"}).status_code == 403
        assert consent(user)

    def test_the_token_does_not_leak_through_the_referer_or_the_cache(self, client, user):
        response = client.get(prefs(token_of(user)))
        assert response["Referrer-Policy"] == "no-referrer" and "no-store" in response["Cache-Control"]

    def test_service_emails_are_said_to_remain(self, client, user):
        assert "restent envoyés" in client.get(prefs(token_of(user))).content.decode()


class TestOneClickUnsubscribe:
    def test_a_mail_client_post_without_csrf_token_opts_out(self, user):
        marketing.set_consent(user, True, "account")
        response = Client(enforce_csrf_checks=True).post(reverse("email_unsubscribe", args=[token_of(user)]), "List-Unsubscribe=One-Click", content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200 and not consent(user)

    def test_it_can_never_opt_back_in(self, client, user):
        marketing.set_consent(user, False, "account")
        client.post(reverse("email_unsubscribe", args=[token_of(user)]), {"choice": "accept"})
        assert not consent(user)

    def test_get_is_refused_and_forged_tokens_are_not_found(self, client, user):
        marketing.set_consent(user, True, "account")
        assert client.get(reverse("email_unsubscribe", args=[token_of(user)])).status_code == 405
        assert client.post(reverse("email_unsubscribe", args=["forged"])).status_code == 404
        assert consent(user)


class TestAccountPage:
    def toggle_tag(self, client):
        import re
        return re.search(r'<input[^>]*name="marketing_opt_in"[^>]*>', client.get(reverse("account")).content.decode()).group(0)

    def test_the_toggle_is_on_by_default_and_reflects_the_choice(self, auth_client, user):
        assert "checked" in self.toggle_tag(auth_client)
        assert 'name="btn_marketing"' in auth_client.get(reverse("account")).content.decode()
        marketing.set_consent(user, False, "account")
        assert "checked" not in self.toggle_tag(auth_client)

    def test_member_can_unsubscribe_then_come_back(self, auth_client, user):
        auth_client.post(reverse("account"), {"btn_marketing": ""})
        assert not consent(user) and BeerUser.objects.get(pk=user.pk).marketing_consent_source == "account"
        auth_client.post(reverse("account"), {"btn_marketing": "", "marketing_opt_in": "on"})
        assert consent(user)

    def test_coming_back_after_an_unsubscription_via_email_is_recorded(self, auth_client, user):
        marketing.set_consent(user, False, "email_link")
        auth_client.post(reverse("account"), {"btn_marketing": "", "marketing_opt_in": "on"})
        assert consent(user)

    def test_notification_settings_do_not_touch_the_consent(self, auth_client, user):
        marketing.set_consent(user, False, "account")
        auth_client.post(reverse("account"), {"btn_notifs": "", "notif_global": "on"})
        assert not consent(user)


class TestAssetLinks:
    def test_served_as_json_at_the_well_known_path(self, client, settings):
        settings.ANDROID_CERT_FINGERPRINTS = ["AA:BB"]
        response = client.get("/.well-known/assetlinks.json")
        assert response.status_code == 200 and response["Content-Type"] == "application/json"
        assert response.json()[0]["target"]["package_name"] == "com.scarone.pokebeer"

    def test_read_only(self, client):
        assert client.post("/.well-known/assetlinks.json").status_code == 405
