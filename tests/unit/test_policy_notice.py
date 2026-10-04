"""Annonce d'une modification de la politique : notification à tous, e-mail facultatif par lots."""
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from app.models import Notification, PolicyNotice, ThrottleHit
from app.services import policy_notice
from app.services.throttle import Rule
from tests import factories as f

pytestmark = pytest.mark.django_db

SUMMARY = "ajout des e-mails de service"


def notified(user):
    return Notification.objects.filter(recipient=user, notif_type="policy_updated")


class TestPublish:
    def test_every_active_member_is_notified_even_with_notifications_disabled(self, user, other_user):
        f.make_user(is_active=False)
        quiet = f.make_user()
        type(quiet).objects.filter(pk=quiet.pk).update(notif_global=False, notif_social=False)
        notice = policy_notice.publish(SUMMARY, False, None)
        assert notice.notified_count == 3
        assert all(notified(member).count() == 1 for member in (user, other_user, quiet))
        assert not Notification.objects.filter(recipient__is_active=False).exists()

    def test_the_notification_opens_the_policy_and_shows_the_summary(self, auth_client, user, settings):
        settings.PRIVACY_POLICY_URL = "https://policy.example/doc"
        policy_notice.publish(SUMMARY, False, None)
        notification = notified(user).get()
        response = auth_client.get(reverse("read_notification", args=[notification.slug]))
        assert response.url == reverse("privacy_policy")  # la notification reste sur le site, qui renvoie vers le document
        assert auth_client.get(response.url).url == "https://policy.example/doc"
        assert SUMMARY in auth_client.get(reverse("notifications")).content.decode()

    def test_no_email_unless_requested(self, user):
        policy_notice.publish(SUMMARY, False, None)
        assert policy_notice.send_pending_emails() == 0 and mail.outbox == []
        assert PolicyNotice.objects.get().email_done

    def test_publishing_twice_in_a_row_is_limited(self, user, monkeypatch):
        monkeypatch.setattr(policy_notice, "POLICY_NOTICE_PUBLISH", Rule("policy-notice", 1, timedelta(days=1)))
        policy_notice.publish(SUMMARY, False, None)
        with pytest.raises(policy_notice.TooManyNotices):
            policy_notice.publish(SUMMARY, False, None)
        assert PolicyNotice.objects.count() == 1


class TestEmails:
    def test_the_email_reaches_each_member_once_with_the_summary_and_the_link(self, user, other_user, settings):
        settings.PRIVACY_POLICY_URL = "https://policy.example/doc"
        policy_notice.publish(SUMMARY, True, None)
        assert policy_notice.send_pending_emails() == 2
        assert sorted(m.to[0] for m in mail.outbox) == sorted([user.email, other_user.email])
        assert SUMMARY in mail.outbox[0].body and "https://policy.example/doc" in mail.outbox[0].body
        assert policy_notice.send_pending_emails() == 0 and len(mail.outbox) == 2
        assert PolicyNotice.objects.get().email_done

    def test_suspended_members_get_nothing(self, user):
        f.make_user(is_active=False)
        policy_notice.publish(SUMMARY, True, None)
        policy_notice.send_pending_emails()
        assert [m.to[0] for m in mail.outbox] == [user.email]

    def test_the_daily_quota_spreads_the_emails_over_several_days(self, monkeypatch):
        monkeypatch.setattr(policy_notice, "POLICY_EMAIL_GLOBAL", Rule("policy-email", 2, timedelta(days=1)))
        for _ in range(5):
            f.make_user()
        policy_notice.publish(SUMMARY, True, None)
        assert policy_notice.send_pending_emails() == 2
        assert not PolicyNotice.objects.get().email_done
        ThrottleHit.objects.update(created_at=timezone.now() - timedelta(days=2))
        assert policy_notice.send_pending_emails() == 2
        ThrottleHit.objects.update(created_at=timezone.now() - timedelta(days=2))
        assert policy_notice.send_pending_emails() == 1
        assert PolicyNotice.objects.get().email_done and len({m.to[0] for m in mail.outbox}) == 5

    def test_a_failure_does_not_block_the_following_members(self, user, other_user):
        from unittest import mock
        policy_notice.publish(SUMMARY, True, None)
        with mock.patch("django.core.mail.message.EmailMultiAlternatives.send", side_effect=[OSError("down"), 1]):
            assert policy_notice.send_pending_emails() == 1
        notice = PolicyNotice.objects.get()
        assert notice.email_done and notice.emails_sent == 1

    def test_the_daily_task_sends_the_next_batch(self, client, settings, user):
        settings.CRON_SECRET = "s3cret"
        policy_notice.publish(SUMMARY, True, None)
        response = client.get(reverse("cron_purge_inactive_accounts"), headers={"Authorization": "Bearer s3cret"})
        assert response.json()["policy_emails"] == 1
