"""E-mail de bienvenue (formulaire, pro, Google) et consentement aux e-mails promotionnels."""
from datetime import timedelta
from unittest import mock

import pytest
from allauth.account.signals import user_signed_up
from django.core import mail, signing
from django.test import TestCase
from django.urls import reverse

from app.models import BeerUser, ThrottleHit
from app.services import app_links, marketing, welcome
from app.services.throttle import Rule
from tests import factories as f
from tests.views.test_auth_views import TestRegister

pytestmark = pytest.mark.django_db


class TestWelcomeEmail:
    def test_it_presents_the_beers_the_map_and_the_notebooks_with_site_links(self, user, settings):
        assert welcome.send_welcome(user)
        message = mail.outbox[0]
        html = message.alternatives[0][0]
        for route in ("all_beers", "map", "notebook"):
            assert f"https://pokebeer.test{reverse(route)}" in message.body and f"https://pokebeer.test{reverse(route)}" in html
        assert message.to == [user.email] and user.username in message.body

    def test_it_never_offers_to_install_the_app(self, user):
        welcome.send_welcome(user)
        message = mail.outbox[0]
        for content in (message.body, message.alternatives[0][0]):
            assert "play.google" not in content.lower() and "installez" not in content.lower() and "google play" not in content.lower()

    def test_it_announces_the_news_and_offers_to_stop_them(self, user):
        welcome.send_welcome(user)
        assert marketing.preferences_url(user) in mail.outbox[0].body and marketing.preferences_url(user) in mail.outbox[0].alternatives[0][0]
        user.refresh_from_db()
        assert user.marketing_opt_in is True and user.marketing_consent_at is None  # reçu par défaut, aucun choix enregistré

    def test_it_is_sent_once_per_account(self, user):
        assert welcome.send_welcome(user) and not welcome.send_welcome(user)
        assert len(mail.outbox) == 1
        user.refresh_from_db()
        assert user.welcome_sent_at is not None

    def test_a_failure_is_swallowed_and_can_be_retried(self, user):
        with mock.patch("django.core.mail.message.EmailMultiAlternatives.send", side_effect=OSError("down")):
            assert welcome.send_welcome(user) is False
        user.refresh_from_db()
        assert user.welcome_sent_at is None
        assert welcome.send_welcome(user)

    def test_the_daily_ceiling_skips_the_email_but_never_the_account(self, user, monkeypatch):
        monkeypatch.setattr(welcome, "WELCOME_EMAIL_GLOBAL", Rule("welcome-email", 1, timedelta(days=1)))
        assert welcome.send_welcome(user) and not welcome.send_welcome(f.make_user())
        assert len(mail.outbox) == 1

    def test_no_marketing_headers_on_a_service_message(self, user):
        welcome.send_welcome(user)
        assert "List-Unsubscribe" not in mail.outbox[0].extra_headers


class TestSignupTriggers:
    def test_form_registration_sends_it(self, client, google_app):
        TestRegister().post(client)
        assert [m.to[0] for m in mail.outbox] == ["newbie@example.test"]

    def test_invalid_registration_sends_nothing(self, client, google_app, user):
        TestRegister().post(client, email=user.email)
        assert mail.outbox == []

    def test_professional_registration_sends_it(self, client):
        data = {
            "user-username": "patron", "user-email": "patron@example.test", "user-password": f.PASSWORD,
            "pro-name": "Chez Patron", "pro-siret": "73282932000074", "pro-description": "Un lieu", "pro-postal_code": "44000",
        }
        client.post(reverse("register_pro", args=["bar"]), data)
        # bienvenue + accusé de réception de la demande de gestion
        assert [m.to[0] for m in mail.outbox] == ["patron@example.test", "patron@example.test"]
        assert any("Bienvenue" in m.subject for m in mail.outbox)

    def test_google_signup_sends_it_once_the_account_is_committed(self):
        member = f.make_user(username="googler")
        with TestCase.captureOnCommitCallbacks(execute=True):
            user_signed_up.send(sender=BeerUser, request=None, user=member)
        assert [m.to[0] for m in mail.outbox] == [member.email]


class TestConsent:
    def test_promotional_emails_are_received_by_default_with_no_recorded_choice(self, user):
        assert user.marketing_opt_in is True and user.marketing_consent_at is None

    def test_the_choice_is_dated_and_its_origin_kept(self, user):
        assert marketing.set_consent(user, False, marketing.ACCOUNT)
        user.refresh_from_db()
        assert not user.marketing_opt_in and user.marketing_consent_at and user.marketing_consent_source == "account"

    def test_repeating_the_same_choice_keeps_the_original_record(self, user):
        marketing.set_consent(user, False, marketing.ACCOUNT)
        first = BeerUser.objects.get(pk=user.pk).marketing_consent_at
        assert not marketing.set_consent(user, False, marketing.EMAIL_LINK)
        member = BeerUser.objects.get(pk=user.pk)
        assert member.marketing_consent_at == first and member.marketing_consent_source == "account"

    def test_coming_back_after_unsubscribing_is_recorded_too(self, user):
        marketing.set_consent(user, False, marketing.EMAIL_LINK)
        assert marketing.set_consent(user, True, marketing.ACCOUNT)
        assert BeerUser.objects.get(pk=user.pk).marketing_opt_in

    def test_tokens_designate_active_members_only(self, user):
        token = marketing.preferences_url(user).rstrip("/").rsplit("/", 1)[1]
        assert marketing.user_for_token(token) == user
        assert marketing.user_for_token(token + "x") is None
        assert marketing.user_for_token(signing.dumps(user.pk, salt="other-purpose")) is None
        BeerUser.objects.filter(pk=user.pk).update(is_active=False)
        assert marketing.user_for_token(token) is None

    def test_unsubscribe_headers_follow_rfc_8058(self, user):
        headers = marketing.unsubscribe_headers(user)
        assert headers["List-Unsubscribe"].startswith(f"<https://pokebeer.test/emails/unsubscribe/")
        assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


class TestAppLinks:
    def test_links_use_the_configured_public_address_only(self):
        assert app_links.site_url("map") == "https://pokebeer.test/map/"

    def test_assetlinks_is_empty_until_fingerprints_are_configured(self, settings):
        settings.ANDROID_CERT_FINGERPRINTS = []
        assert app_links.assetlinks() == []

    def test_assetlinks_binds_the_domain_to_the_android_package(self, settings):
        settings.ANDROID_CERT_FINGERPRINTS = ["AA:BB"]
        (statement,) = app_links.assetlinks()
        assert statement["target"] == {"namespace": "android_app", "package_name": "com.scarone.pokebeer", "sha256_cert_fingerprints": ["AA:BB"]}
