"""Réinitialisation du mot de passe : sécurité du parcours complet (demande, e-mail, lien, confirmation)."""
import re
from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from app.models import BeerUser, ThrottleHit
from app.services import password_reset
from app.services.throttle import PASSWORD_RESET_BY_EMAIL, PASSWORD_RESET_BY_IP, PASSWORD_RESET_CONFIRM_BY_IP, Rule
from tests import factories as f

pytestmark = pytest.mark.django_db

REQUEST = "password_reset"
NEW_PASSWORD = "Nouveau-Mdp-Solide-2026!"
IP = {"REMOTE_ADDR": "198.51.100.20"}


def ask(client, email, **extra):
    return client.post(reverse(REQUEST), {"email": email}, **(extra or IP))


def link_in(message):
    return re.search(r"https://pokebeer\.test(/password-reset/[\w-]+/[\w-]+/)", message.body).group(1)


def google_member(username="gus"):
    member = f.make_user(username=username)
    member.set_unusable_password()
    member.save()
    return member


class TestRequest:
    def test_member_receives_a_link_that_leads_to_the_reset_form(self, client, user):
        response = ask(client, user.email)
        assert response.status_code == 302 and response.url == reverse("password_reset_done")
        (message,) = mail.outbox
        assert message.to == [user.email] and message.reply_to == ["pokebeer.assistance@gmail.com"]
        assert any(mime == "text/html" for _, mime in message.alternatives)
        page = client.get(link_in(message), follow=True)
        assert page.status_code == 200 and page.context["validlink"]

    def test_link_uses_the_configured_address_never_the_request_host(self, client, user, settings):
        settings.ALLOWED_HOSTS = ["*"]
        client.post(reverse(REQUEST), {"email": user.email}, HTTP_HOST="evil.example", **IP)
        assert "evil.example" not in mail.outbox[0].body and "https://pokebeer.test/password-reset/" in mail.outbox[0].body

    def test_email_is_matched_without_regard_to_case(self, client, user):
        ask(client, user.email.upper())
        assert len(mail.outbox) == 1

    def test_unknown_address_gets_the_same_answer_and_no_mail(self, client, user):
        known = ask(client, user.email)
        unknown = ask(client, "nobody@example.test")
        assert (known.status_code, known.url) == (unknown.status_code, unknown.url)
        assert len(mail.outbox) == 1

    def test_the_confirmation_page_never_says_whether_an_account_exists(self, client, user):
        page = client.get(reverse("password_reset_done")).content.decode()
        assert "Si un compte correspond" in page

    def test_suspended_accounts_receive_nothing(self, client):
        member = f.make_user(is_active=False)
        assert ask(client, member.email).status_code == 302
        assert mail.outbox == []

    def test_malformed_addresses_are_refused_without_sending(self, client):
        assert ask(client, "not-an-email").status_code == 200
        assert mail.outbox == []

    def test_a_mail_server_failure_is_invisible_to_the_visitor(self, client, user):
        with mock.patch("django.core.mail.message.EmailMultiAlternatives.send", side_effect=OSError("SMTP down")):
            response = ask(client, user.email)
        assert response.status_code == 302 and response.url == reverse("password_reset_done")

    def test_the_response_takes_a_minimum_time(self, client, user, settings):
        settings.PASSWORD_RESET_MIN_SECONDS = 2
        with mock.patch("app.services.timing.time.sleep") as sleep:
            ask(client, "nobody@example.test")
        assert sleep.called and 0 < sleep.call_args.args[0] <= 2


class TestGoogleAccounts:
    def test_google_member_gets_a_reminder_and_never_a_reset_link(self, client):
        member = google_member()
        ask(client, member.email)
        (message,) = mail.outbox
        body = message.body + "".join(content for content, _ in message.alternatives)
        assert "Google" in body and "/password-reset/" not in body

    def test_a_forged_link_for_a_google_member_is_refused(self, client):
        member = google_member()
        uid = urlsafe_base64_encode(force_bytes(member.pk))
        url = reverse("password_reset_confirm", args=[uid, default_token_generator.make_token(member)])
        page = client.get(url, follow=True)
        assert not page.context["validlink"]
        assert client.post(page.request["PATH_INFO"], {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}).status_code == 200
        member.refresh_from_db()
        assert not member.has_usable_password()

    def test_allauth_pages_that_set_a_password_are_redirected_away(self, client):
        assert client.get("/accounts/password/reset/").url == reverse(REQUEST)
        assert client.get("/accounts/password/set/").url == reverse("account")
        assert client.get("/accounts/password/change/").url == reverse("account")


class TestThrottling:
    def test_ip_is_refused_explicitly_after_too_many_requests(self, client):
        for index in range(PASSWORD_RESET_BY_IP.attempts):
            ask(client, f"x{index}@example.test")
        assert ask(client, "late@example.test").status_code == 429

    def test_the_same_address_stops_receiving_mail_without_any_signal(self, client, user):
        statuses = [ask(client, user.email, REMOTE_ADDR=f"203.0.113.{i}").status_code for i in range(PASSWORD_RESET_BY_EMAIL.attempts + 2)]
        assert set(statuses) == {302}
        assert len(mail.outbox) == PASSWORD_RESET_BY_EMAIL.attempts

    def test_requests_for_unknown_addresses_count_too(self, client):
        for _ in range(PASSWORD_RESET_BY_EMAIL.attempts):
            ask(client, "ghost@example.test")
        assert PASSWORD_RESET_BY_EMAIL.exceeded("ghost@example.test")

    def test_daily_ceiling_protects_the_mail_quota(self, client, monkeypatch):
        monkeypatch.setattr(password_reset, "PASSWORD_RESET_GLOBAL", Rule("reset-global", 2, timedelta(days=1)))
        members = [f.make_user() for _ in range(4)]
        for index, member in enumerate(members):
            ask(client, member.email, REMOTE_ADDR=f"203.0.113.{index}")
        assert len(mail.outbox) == 2

    def test_only_hashed_keys_are_stored(self, client, user):
        ask(client, user.email)
        assert not any(user.email in hit.key_hash for hit in ThrottleHit.objects.all())


class TestConfirmation:
    def start(self, client, user):
        ask(client, user.email)
        return client.get(link_in(mail.outbox[-1]), follow=True).request["PATH_INFO"]

    def change(self, client, form_url, password=NEW_PASSWORD, **extra):
        return client.post(form_url, {"new_password1": password, "new_password2": password}, **(extra or IP))

    def test_the_password_changes_and_the_old_one_stops_working(self, client, user):
        form_url = self.start(client, user)
        assert self.change(client, form_url).url == reverse("password_reset_complete")
        user.refresh_from_db()
        assert user.check_password(NEW_PASSWORD) and not user.check_password(f.PASSWORD)

    def test_the_link_works_only_once(self, client, user):
        link = link_in((ask(client, user.email), mail.outbox[-1])[1])
        form_url = client.get(link, follow=True).request["PATH_INFO"]
        self.change(client, form_url)
        assert not client.get(link, follow=True).context["validlink"]

    def test_the_token_is_removed_from_the_address_bar_before_the_form(self, client, user):
        ask(client, user.email)
        link = link_in(mail.outbox[-1])
        response = client.get(link)
        assert response.status_code == 302 and "set-password" in response.url and link.split("/")[-2] not in response.url

    def test_an_expired_link_is_refused(self, client, user, settings):
        ask(client, user.email)
        settings.PASSWORD_RESET_TIMEOUT = -1
        assert not client.get(link_in(mail.outbox[-1]), follow=True).context["validlink"]

    def test_logging_in_invalidates_a_pending_link(self, client, user, client_for):
        ask(client, user.email)
        client_for(user)  # force_login met à jour last_login
        assert not client.get(link_in(mail.outbox[-1]), follow=True).context["validlink"]

    def test_other_sessions_are_logged_out(self, client, user, client_for):
        elsewhere = client_for(user)
        form_url = self.start(client, user)
        self.change(client, form_url)
        assert elsewhere.get(reverse("account")).status_code == 302

    def test_the_member_is_warned_by_mail(self, client, user):
        form_url = self.start(client, user)
        mail.outbox.clear()
        self.change(client, form_url)
        (message,) = mail.outbox
        assert message.to == [user.email] and "modifié" in message.subject

    @pytest.mark.parametrize("password", ["short", "password", "12345678", "alice123"])
    def test_weak_passwords_are_refused(self, client, user, password):
        form_url = self.start(client, user)
        assert self.change(client, form_url, password).status_code == 200
        user.refresh_from_db()
        assert user.check_password(f.PASSWORD)

    def test_mismatching_confirmation_is_refused(self, client, user):
        form_url = self.start(client, user)
        response = client.post(form_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD + "x"}, **IP)
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.check_password(f.PASSWORD)

    def test_garbage_links_are_refused(self, client):
        page = client.get(reverse("password_reset_confirm", args=["MQ", "abc-123"]), follow=True)
        assert not page.context["validlink"] and "Lien invalide" in page.content.decode()

    def test_attempts_are_limited_per_ip(self, client, user):
        form_url = self.start(client, user)
        for _ in range(PASSWORD_RESET_CONFIRM_BY_IP.attempts):
            self.change(client, form_url, "short")
        assert self.change(client, form_url).status_code == 429


class TestPasswordChangeFromTheAccountPage:
    def test_the_member_is_warned_by_mail(self, auth_client, user):
        auth_client.post(reverse("account"), {
            "btn_password": "1", "old_password": f.PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD,
        })
        assert [m.to for m in mail.outbox] == [[user.email]] and "modifié" in mail.outbox[0].subject


def test_login_page_links_to_the_reset(client, google_app):
    assert reverse(REQUEST) in client.get(reverse("login")).content.decode()


def test_mail_settings_use_gmail_over_tls_and_never_the_account_password():
    import importlib
    import os

    import pokebeer.settings as module
    with mock.patch.dict(os.environ, {"EMAIL_HOST_PASSWORD": "app-password-123"}), mock.patch("pokebeer.database.get_databases", return_value={}):
        configured = importlib.reload(module)
        assert configured.EMAIL_BACKEND.endswith("smtp.EmailBackend")
        assert (configured.EMAIL_HOST, configured.EMAIL_PORT, configured.EMAIL_USE_TLS) == ("smtp.gmail.com", 587, True)
        assert configured.DEFAULT_FROM_EMAIL.endswith("<pokebeer.assistance@gmail.com>")
    env = {k: v for k, v in os.environ.items() if k != "EMAIL_HOST_PASSWORD"}
    with mock.patch.dict(os.environ, env, clear=True), mock.patch("pokebeer.database.get_databases", return_value={}):
        assert importlib.reload(module).EMAIL_BACKEND.endswith("console.EmailBackend")
    importlib.reload(module)
