"""RGPD : avertissement puis suppression des comptes inactifs."""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from app.models import AccountDeletion, BeerUser, Notification
from app.services import inactivity
from tests import factories as f

pytestmark = pytest.mark.django_db

LONG_AGO = timedelta(days=24 * 31)  # > 24 mois
IN_WARNING_WINDOW = timedelta(days=24 * 30 + 5)  # < 24 mois mais dans les 30 derniers jours


def idle(user, delta, warned_days_ago=None):
    BeerUser.objects.filter(pk=user.pk).update(
        last_activity_at=timezone.now() - delta,
        inactivity_warned_at=timezone.now() - timedelta(days=warned_days_ago) if warned_days_ago is not None else None,
    )
    user.refresh_from_db()
    return user


def exists(user):
    return BeerUser.objects.filter(pk=user.pk).exists()


class TestWarning:
    def test_member_entering_the_window_is_notified_once(self, user):
        idle(user, IN_WARNING_WINDOW)
        assert inactivity.purge_inactive_accounts() == (1, 0)
        notif = Notification.objects.get(recipient=user, notif_type="inactivity_warning")
        assert notif.text_content
        assert inactivity.purge_inactive_accounts() == (0, 0)
        assert Notification.objects.filter(notif_type="inactivity_warning").count() == 1

    def test_warning_ignores_notification_preferences(self, user):
        BeerUser.objects.filter(pk=user.pk).update(notif_global=False)
        idle(user, IN_WARNING_WINDOW)
        inactivity.purge_inactive_accounts()
        assert Notification.objects.filter(recipient=user, notif_type="inactivity_warning").exists()

    def test_active_member_is_left_alone(self, user):
        assert inactivity.purge_inactive_accounts() == (0, 0)
        assert not Notification.objects.exists()


class TestDeletion:
    def test_unwarned_member_is_warned_first_never_deleted_without_notice(self, user):
        idle(user, LONG_AGO)
        assert inactivity.purge_inactive_accounts() == (1, 0)
        assert exists(user)

    def test_member_is_deleted_once_the_notice_has_elapsed(self, user):
        idle(user, LONG_AGO, warned_days_ago=31)
        assert inactivity.purge_inactive_accounts() == (0, 1)
        assert not exists(user)

    def test_member_is_kept_during_the_notice(self, user):
        idle(user, LONG_AGO, warned_days_ago=10)
        assert inactivity.purge_inactive_accounts() == (0, 0)
        assert exists(user)

    def test_deletion_is_logged_without_personal_data(self, user):
        idle(user, LONG_AGO, warned_days_ago=31)
        pk = user.pk
        inactivity.purge_inactive_accounts()
        entry = AccountDeletion.objects.get()
        assert (entry.user_id, entry.reason, entry.was_warned) == (pk, "inactivity", True)
        assert {field.name for field in AccountDeletion._meta.fields} == {
            "id", "user_id", "reason", "last_activity_at", "was_warned", "deleted_at",
        }

    @pytest.mark.parametrize("make", [
        lambda: f.make_user(is_superuser=True),
        lambda: f.make_user(groups=("Staff",)),
        lambda: f.make_user(is_active=False),
    ])
    def test_protected_accounts_are_never_deleted(self, make):
        member = idle(make(), LONG_AGO, warned_days_ago=60)
        assert inactivity.purge_inactive_accounts() == (0, 0)
        assert exists(member)

    def test_one_failure_does_not_block_the_others(self, monkeypatch):
        first, second = (idle(f.make_user(), LONG_AGO, warned_days_ago=31) for _ in range(2))
        real = BeerUser.delete

        def flaky(self, *args, **kwargs):
            if self.pk == first.pk:
                raise RuntimeError("boom")
            return real(self, *args, **kwargs)

        monkeypatch.setattr(BeerUser, "delete", flaky)
        assert inactivity.purge_inactive_accounts()[1] == 1
        assert exists(first) and not exists(second)
        assert not AccountDeletion.objects.filter(user_id=first.pk).exists()


class TestActivity:
    def test_a_visit_cancels_the_warning_and_removes_the_notification(self, user, client_for):
        idle(user, IN_WARNING_WINDOW)
        inactivity.purge_inactive_accounts()
        assert client_for(user).get(reverse("account")).status_code == 200
        user.refresh_from_db()
        assert user.inactivity_warned_at is None
        assert timezone.now() - user.last_activity_at < timedelta(minutes=1)
        assert not Notification.objects.filter(notif_type="inactivity_warning").exists()
        assert inactivity.purge_inactive_accounts() == (0, 0)

    def test_recent_activity_is_not_rewritten_on_every_request(self, user, client_for):
        before = user.last_activity_at
        client_for(user).get(reverse("account"))
        user.refresh_from_db()
        assert user.last_activity_at == before

    def test_stale_activity_is_refreshed(self, user, client_for):
        idle(user, timedelta(days=3))
        client_for(user).get(reverse("account"))
        user.refresh_from_db()
        assert timezone.now() - user.last_activity_at < timedelta(minutes=1)


class TestSelfDeletion:
    def test_manual_deletion_is_logged(self, user, client_for):
        pk = user.pk
        client_for(user).post(reverse("delete_account"))
        entry = AccountDeletion.objects.get()
        assert (entry.user_id, entry.reason) == (pk, "self")


class TestCronEndpoint:
    url = "cron_purge_inactive_accounts"

    def test_closed_without_a_configured_secret(self, client, settings):
        settings.CRON_SECRET = None
        assert client.get(reverse(self.url)).status_code == 403
        assert client.get(reverse(self.url), headers={"Authorization": "Bearer None"}).status_code == 403

    def test_refuses_a_wrong_secret(self, client, settings):
        settings.CRON_SECRET = "s3cret"
        assert client.get(reverse(self.url), headers={"Authorization": "Bearer nope"}).status_code == 403

    def test_runs_with_the_secret(self, client, settings, user):
        settings.CRON_SECRET = "s3cret"
        idle(user, LONG_AGO, warned_days_ago=31)
        response = client.get(reverse(self.url), headers={"Authorization": "Bearer s3cret"})
        assert response.json() == {"warned": 0, "deleted": 1, "policy_emails": 0}

    def test_get_only(self, client, settings):
        settings.CRON_SECRET = "s3cret"
        assert client.post(reverse(self.url), headers={"Authorization": "Bearer s3cret"}).status_code == 405


def test_command_dry_run_changes_nothing(user, capsys):
    idle(user, LONG_AGO, warned_days_ago=31)
    call_command("purge_inactive_accounts", "--dry-run")
    assert exists(user) and "à supprimer : 1" in capsys.readouterr().out


def test_command_purges(user):
    idle(user, LONG_AGO, warned_days_ago=31)
    call_command("purge_inactive_accounts")
    assert not exists(user)


def test_month_arithmetic_clamps_to_month_end():
    from datetime import datetime, timezone as tz
    assert inactivity._months_before(datetime(2026, 3, 31, tzinfo=tz.utc), 1).day == 28
    assert inactivity._months_before(datetime(2026, 10, 4, tzinfo=tz.utc), 24).year == 2024


class TestInactivityEmails:
    """Avertissement et confirmation par e-mail, en plus de la notification dans l'application."""

    def warned_user(self, member, **kwargs):
        return idle(member, IN_WARNING_WINDOW, **kwargs)

    def test_warning_goes_by_email_and_by_notification(self, user):
        from django.core import mail
        self.warned_user(user)
        assert inactivity.purge_inactive_accounts() == (1, 0)
        (message,) = mail.outbox
        assert message.to == [user.email] and "supprimé pour inactivité" in message.subject
        assert Notification.objects.filter(recipient=user, notif_type="inactivity_warning").exists()
        deadline = Notification.objects.get(recipient=user).text_content
        assert deadline in message.body and user.username in message.body
        assert any(deadline in content for content, _ in message.alternatives)
        assert "https://pokebeer.test/login/" in message.body

    def test_the_member_is_warned_only_once(self, user):
        from django.core import mail
        self.warned_user(user)
        inactivity.purge_inactive_accounts()
        inactivity.purge_inactive_accounts()
        assert len(mail.outbox) == 1

    def test_a_mail_failure_does_not_prevent_the_in_app_warning(self, user):
        from unittest import mock
        self.warned_user(user)
        with mock.patch("django.core.mail.message.EmailMultiAlternatives.send", side_effect=OSError("SMTP down")):
            assert inactivity.purge_inactive_accounts() == (1, 0)
        user.refresh_from_db()
        assert user.inactivity_warned_at is not None and Notification.objects.filter(recipient=user).exists()

    def test_a_member_nobody_could_reach_is_retried_and_never_deleted(self, user, monkeypatch):
        from unittest import mock
        self.warned_user(user)
        monkeypatch.setattr(inactivity, "notify", lambda *args, **kwargs: [])
        with mock.patch("django.core.mail.message.EmailMultiAlternatives.send", side_effect=OSError("SMTP down")):
            assert inactivity.purge_inactive_accounts() == (0, 0)
        user.refresh_from_db()
        assert user.inactivity_warned_at is None
        assert exists(user)  # jamais supprimé sans préavis
        monkeypatch.undo()
        assert inactivity.purge_inactive_accounts() == (1, 0)  # repris à la prochaine exécution

    def test_the_daily_ceiling_defers_the_remaining_members_to_the_next_run(self, monkeypatch):
        from datetime import timedelta as delta
        from django.core import mail
        from app.services import inactivity_mail
        from app.services.throttle import Rule
        monkeypatch.setattr(inactivity_mail, "INACTIVITY_EMAIL_GLOBAL", Rule("inactivity-email", 2, delta(days=1)))
        members = [self.warned_user(f.make_user()) for _ in range(4)]
        assert inactivity.purge_inactive_accounts() == (2, 0)
        assert len(mail.outbox) == 2
        assert sum(BeerUser.objects.get(pk=m.pk).inactivity_warned_at is not None for m in members) == 2
        # le lendemain, le plafond est reparti
        from app.models import ThrottleHit
        ThrottleHit.objects.update(created_at=timezone.now() - delta(days=2))
        assert inactivity.purge_inactive_accounts() == (2, 0)
        assert len(mail.outbox) == 4

    def test_a_deletion_notice_is_sent_once_the_account_is_gone(self, user):
        from django.core import mail
        email, username = user.email, user.username
        idle(user, LONG_AGO, warned_days_ago=31)
        assert inactivity.purge_inactive_accounts() == (0, 1)
        (message,) = mail.outbox
        assert message.to == [email] and "supprimé" in message.subject and username in message.body
        assert not BeerUser.objects.filter(email=email).exists()

    def test_protected_accounts_receive_nothing(self):
        from django.core import mail
        for member in (f.make_user(is_superuser=True), f.make_user(groups=("Staff",)), f.make_user(is_active=False)):
            idle(member, LONG_AGO, warned_days_ago=60)
        inactivity.purge_inactive_accounts()
        assert mail.outbox == []

    def test_a_failed_deletion_sends_no_notice(self, user, monkeypatch):
        from django.core import mail
        idle(user, LONG_AGO, warned_days_ago=31)
        monkeypatch.setattr(BeerUser, "delete", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
        assert inactivity.purge_inactive_accounts() == (0, 0)
        assert mail.outbox == []

    def test_dashboard_tells_when_mail_is_not_configured(self, settings):
        settings.EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
        assert inactivity.dashboard_stats()["email_enabled"] is False
        settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
        assert inactivity.dashboard_stats()["email_enabled"] is True
