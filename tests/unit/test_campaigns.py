"""Campagnes e-mail : audiences, consentement, envoi par lots, annulation."""
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from app.models import CampaignRecipient, EmailCampaign, ThrottleHit
from app.services import campaigns, marketing
from app.services.throttle import Rule
from tests import factories as f

pytestmark = pytest.mark.django_db

PROMO, SERVICE = EmailCampaign.Kind.PROMOTIONAL, EmailCampaign.Kind.SERVICE
ALL, ACTIVE, INACTIVE, CUSTOM = EmailCampaign.Audience.ALL, EmailCampaign.Audience.ACTIVE, EmailCampaign.Audience.INACTIVE, EmailCampaign.Audience.CUSTOM


@pytest.fixture
def user(db):
    """L'administrateur qui lance les campagnes : désinscrit, pour ne pas compter parmi les destinataires."""
    return f.make_user(username="alice", marketing_opt_in=False)


def member(opt_in=True, days_idle=0, **fields):
    created = f.make_user(marketing_opt_in=opt_in, **fields)
    type(created).objects.filter(pk=created.pk).update(last_activity_at=timezone.now() - timedelta(days=days_idle))
    return created


def campaign(kind=PROMO, audience=ALL, **fields):
    fields.setdefault("subject", "Du nouveau")
    fields.setdefault("body", "Bonjour {username}, découvrez nos bières.\n\nÀ bientôt !")
    return EmailCampaign.objects.create(kind=kind, audience=audience, **fields)


def emails():
    return sorted(m.to[0] for m in mail.outbox)


class TestAudience:
    def test_promotional_reaches_everyone_except_unsubscribed_members(self):
        yes, no = member(True), member(False)
        assert list(campaigns.audience_for(campaign())) == [yes] and no not in campaigns.audience_for(campaign())

    def test_a_mandatory_alert_reaches_everyone_active_regardless_of_consent(self):
        yes, no = member(True), member(False)
        member(True, is_active=False)
        assert set(campaigns.audience_for(campaign(kind=SERVICE))) == {yes, no}

    def test_suspended_members_never_receive_promotions(self):
        member(True, is_active=False)
        assert not campaigns.audience_for(campaign()).exists()

    def test_active_and_inactive_split_on_the_threshold(self):
        recent, old = member(days_idle=10), member(days_idle=200)
        assert list(campaigns.audience_for(campaign(audience=ACTIVE, activity_days=90))) == [recent]
        assert list(campaigns.audience_for(campaign(audience=INACTIVE, activity_days=90))) == [old]

    def test_custom_list_reaches_only_the_chosen_members(self):
        a, b, outsider = member(), member(), member()
        custom = campaign(audience=CUSTOM)
        custom.custom_members.set([a, b])
        assert set(campaigns.audience_for(custom)) == {a, b} and outsider not in campaigns.audience_for(custom)

    def test_a_chosen_member_who_unsubscribed_is_left_out_of_a_promotion(self):
        keeps, left = member(), member(False)
        custom = campaign(audience=CUSTOM)
        custom.custom_members.set([keeps, left])
        assert list(campaigns.audience_for(custom)) == [keeps] and campaigns.preview(custom).no_consent == 1

    def test_preview_counts_the_unsubscribed_members_left_out(self):
        member(True), member(False), member(False)
        result = campaigns.preview(campaign())
        assert (result.recipients, result.no_consent) == (1, 2)



class TestLaunch:
    def test_it_freezes_the_recipients_and_forgets_the_typed_list(self, user):
        target = member(username="alpha")
        draft = campaign(audience=CUSTOM)
        draft.custom_members.set([target])
        sent = campaigns.launch(draft, user)
        assert sent.status == EmailCampaign.Status.SENDING and sent.launched_by == user and not sent.custom_members.exists()
        assert list(sent.recipients.values_list("user", flat=True)) == [target.pk]

    def test_an_empty_audience_cannot_be_launched(self, user):
        member(False)
        with pytest.raises(campaigns.CampaignError):
            campaigns.launch(campaign(), user)
        assert EmailCampaign.objects.get().status == EmailCampaign.Status.DRAFT

    def test_a_campaign_launches_only_once(self, user):
        member()
        launched = campaigns.launch(campaign(), user)
        with pytest.raises(campaigns.CampaignError):
            campaigns.launch(launched, user)
        assert launched.recipients.count() == 1

    def test_repeated_launches_are_limited(self, user, monkeypatch):
        monkeypatch.setattr(campaigns, "CAMPAIGN_LAUNCH", Rule("campaign-launch", 1, timedelta(days=1)))
        member()
        campaigns.launch(campaign(), user)
        with pytest.raises(campaigns.TooManyLaunches):
            campaigns.launch(campaign(), user)


class TestSending:
    def test_each_recipient_gets_one_personalised_email_and_the_campaign_completes(self, user):
        a, b = member(username="alpha"), member(username="bravo")
        launched = campaigns.launch(campaign(), user)
        assert campaigns.send_batch(launched) == 2
        assert emails() == sorted([a.email, b.email])
        assert any("Bonjour alpha," in m.body for m in mail.outbox) and any("Bonjour bravo," in m.body for m in mail.outbox)
        assert EmailCampaign.objects.get().status == EmailCampaign.Status.DONE and EmailCampaign.objects.get().finished_at
        assert campaigns.send_batch(launched) == 0 and len(mail.outbox) == 2

    def test_promotional_emails_carry_the_unsubscribe_machinery(self, user):
        target = member()
        campaigns.send_batch(campaigns.launch(campaign(), user))
        message = mail.outbox[0]
        assert message.extra_headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
        assert marketing.unsubscribe_url(target) == message.extra_headers["List-Unsubscribe"].split(">")[0].lstrip("<")
        assert marketing.preferences_url(target) in message.body
        assert "play.google" not in message.body and "installez" not in message.body.lower()

    def test_a_mandatory_alert_has_no_unsubscribe_link(self, user):
        member(False)
        campaigns.send_batch(campaigns.launch(campaign(kind=SERVICE), user))
        message = mail.outbox[0]
        assert "List-Unsubscribe" not in message.extra_headers and "emails/preferences" not in message.body

    def test_the_button_links_to_the_site_without_any_install_hint(self, user):
        member()
        campaigns.send_batch(campaigns.launch(campaign(cta_label="Voir la carte", cta_url="https://pokebeer.test/map/"), user))
        assert "Voir la carte : https://pokebeer.test/map/" in mail.outbox[0].body and "Android" not in mail.outbox[0].body

    def test_content_is_escaped_in_html(self, user):
        member()
        campaigns.send_batch(campaigns.launch(campaign(body="<script>alert(1)</script> {username}"), user))
        html = mail.outbox[0].alternatives[0][0]
        assert "<script>" not in html and "&lt;script&gt;" in html

    def test_someone_who_unsubscribes_after_launch_is_skipped(self, user):
        stays, leaves = member(), member()
        launched = campaigns.launch(campaign(), user)
        marketing.set_consent(leaves, False, marketing.EMAIL_LINK)
        assert campaigns.send_batch(launched) == 1 and emails() == [stays.email]
        assert launched.recipients.get(user=leaves).status == CampaignRecipient.Status.SKIPPED

    def test_a_suspended_member_is_skipped(self, user):
        gone = member()
        launched = campaigns.launch(campaign(), user)
        type(gone).objects.filter(pk=gone.pk).update(is_active=False)
        assert campaigns.send_batch(launched) == 0 and mail.outbox == []

    def test_the_daily_quota_spreads_the_sending_over_several_days(self, user, monkeypatch):
        monkeypatch.setattr(campaigns, "CAMPAIGN_EMAIL_GLOBAL", Rule("campaign-email", 2, timedelta(days=1)))
        for _ in range(5):
            member()
        launched = campaigns.launch(campaign(), user)
        assert campaigns.send_pending() == 2 and EmailCampaign.objects.get().status == EmailCampaign.Status.SENDING
        for expected in (2, 1):
            ThrottleHit.objects.update(created_at=timezone.now() - timedelta(days=2))
            assert campaigns.send_pending() == expected
        assert EmailCampaign.objects.get().status == EmailCampaign.Status.DONE and len(set(emails())) == 5

    def test_a_batch_limit_is_respected(self, user):
        for _ in range(3):
            member()
        assert campaigns.send_batch(campaigns.launch(campaign(), user), limit=2) == 2
        assert EmailCampaign.objects.get().status == EmailCampaign.Status.SENDING

    def test_a_failed_delivery_is_marked_and_never_retried(self, user, monkeypatch):
        from unittest import mock
        member(), member()
        launched = campaigns.launch(campaign(), user)
        with mock.patch("django.core.mail.message.EmailMultiAlternatives.send", side_effect=[OSError("down"), 1]):
            assert campaigns.send_batch(launched) == 1
        assert sorted(launched.recipients.values_list("status", flat=True)) == ["failed", "sent"]
        assert campaigns.send_batch(launched) == 0

    def test_a_recipient_reserved_elsewhere_is_never_written_twice(self, user):
        member()
        launched = campaigns.launch(campaign(), user)
        launched.recipients.update(status=CampaignRecipient.Status.SENDING)
        assert campaigns.send_batch(launched) == 0 and mail.outbox == []

    def test_a_draft_does_not_send(self, user):
        member()
        assert campaigns.send_batch(campaign()) == 0


class TestCancelAndTest:
    def test_cancelling_skips_the_remaining_recipients(self, user):
        for _ in range(3):
            member()
        launched = campaigns.launch(campaign(), user)
        campaigns.send_batch(launched, limit=1)
        campaigns.cancel(launched)
        assert campaigns.send_batch(launched) == 0 and len(mail.outbox) == 1
        assert EmailCampaign.objects.get().status == EmailCampaign.Status.CANCELLED
        assert launched.recipients.filter(status="skipped").count() == 2

    def test_a_finished_campaign_cannot_be_cancelled(self, user):
        member()
        launched = campaigns.launch(campaign(), user)
        campaigns.send_batch(launched)
        with pytest.raises(campaigns.CampaignError):
            campaigns.cancel(launched)

    def test_the_test_goes_to_the_admin_only_and_is_labelled(self, user):
        member()
        assert campaigns.send_test(campaign(), user)
        assert [m.to[0] for m in mail.outbox] == [user.email] and mail.outbox[0].subject == "[TEST] Du nouveau"

    def test_the_daily_task_runs_the_campaigns(self, client, settings, user):
        settings.CRON_SECRET = "s3cret"
        member()
        campaigns.launch(campaign(), user)
        from django.urls import reverse
        response = client.get(reverse("cron_purge_inactive_accounts"), headers={"Authorization": "Bearer s3cret"})
        assert response.json()["campaign_emails"] == 1
