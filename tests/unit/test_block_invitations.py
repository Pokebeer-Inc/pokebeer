import pytest

from app.models import Notification, UserBlock
from app.services.blocks import REPEATED_BLOCK_THRESHOLD, invite_blockers_to_report
from tests import factories as f

pytestmark = pytest.mark.django_db


def blockers(target, count):
    return [f.block(f.make_user(username=f.unique("b_")), target).blocker for _ in range(count)]


def invitations():
    return Notification.objects.filter(notif_type="block_follow_up")


class TestInviteBlockersToReport:
    def test_nothing_below_the_threshold(self, other_user):
        blockers(other_user, REPEATED_BLOCK_THRESHOLD - 1)
        assert invite_blockers_to_report(other_user) == [] and not invitations().exists()

    def test_every_blocker_is_invited_once_the_threshold_is_reached(self, other_user):
        members = blockers(other_user, REPEATED_BLOCK_THRESHOLD)
        invite_blockers_to_report(other_user)
        assert {n.recipient for n in invitations()} == set(members)
        assert all(n.text_content == other_user.username for n in invitations())
        assert UserBlock.objects.filter(report_invited_at__isnull=True).count() == 0

    def test_invitation_is_sent_only_once_per_blocker(self, other_user):
        blockers(other_user, REPEATED_BLOCK_THRESHOLD)
        invite_blockers_to_report(other_user)
        invite_blockers_to_report(other_user)
        late = blockers(other_user, 1)[0]
        invite_blockers_to_report(other_user)
        assert invitations().count() == REPEATED_BLOCK_THRESHOLD + 1
        assert invitations().filter(recipient=late).count() == 1

    def test_blocked_member_is_never_notified(self, other_user):
        blockers(other_user, REPEATED_BLOCK_THRESHOLD)
        invite_blockers_to_report(other_user)
        assert not Notification.objects.filter(recipient=other_user).exists()

    def test_message_reveals_neither_count_nor_other_blockers(self, other_user, client_for):
        members = blockers(other_user, REPEATED_BLOCK_THRESHOLD)
        invite_blockers_to_report(other_user)
        from django.template.loader import render_to_string
        text = render_to_string("partials/notification_text.html", {"notif": invitations().first()})
        assert str(REPEATED_BLOCK_THRESHOLD) not in text
        assert not any(m.username in text for m in members if m != invitations().first().recipient)

    def test_notification_leads_to_the_blocked_list(self, other_user):
        blockers(other_user, REPEATED_BLOCK_THRESHOLD)
        invite_blockers_to_report(other_user)
        from django.urls import reverse
        from app.services import notification_types
        assert notification_types.get("block_follow_up").url_for(invitations().first()) == reverse("blocked_users")


class TestBlockViewFlow:
    def test_third_block_triggers_the_invitations(self, client_for, other_user):
        blockers(other_user, REPEATED_BLOCK_THRESHOLD - 1)
        third = f.make_user(username=f.unique("third_"))
        from django.urls import reverse
        client_for(third).post(reverse("block_user", args=[other_user.username]))
        assert invitations().count() == REPEATED_BLOCK_THRESHOLD

    def test_blocked_page_offers_to_report_right_after_blocking(self, auth_client, user, other_user):
        from django.urls import reverse
        f.block(user, other_user)
        response = auth_client.get(reverse("blocked_users"), {"just_blocked": other_user.username})
        html = response.content.decode()
        assert response.context["just_blocked"] == other_user.username
        assert "Signaler à l'équipe" in html and 'name="item_type" value="user"' in html

    def test_hint_is_ignored_for_a_member_not_blocked_by_the_user(self, auth_client, other_user):
        from django.urls import reverse
        response = auth_client.get(reverse("blocked_users"), {"just_blocked": other_user.username})
        assert response.context["just_blocked"] is None and "Signaler à l'équipe" not in response.content.decode()
