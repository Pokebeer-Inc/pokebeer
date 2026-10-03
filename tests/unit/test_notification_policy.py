import pytest

from app.models import Notification, UserBlock
from app.services import notification_types
from app.services.notifications import create_notifications, notify
from tests import factories as f

pytestmark = pytest.mark.django_db


class TestRegistry:
    def test_every_type_has_a_preference_or_is_a_system_message(self):
        categories = {t.category for t in notification_types.REGISTRY.values()} - {None}
        assert categories <= set(notification_types.CATEGORY_FIELDS)

    def test_model_choices_come_from_the_registry(self):
        assert Notification.NOTIFICATION_TYPES == notification_types.CHOICES

    def test_every_preference_is_a_user_field(self, user):
        for field in notification_types.CATEGORY_FIELDS:
            assert isinstance(getattr(user, field), bool)

    def test_unknown_type_is_rejected_loudly(self, user):
        with pytest.raises(KeyError):
            f.make_notification(user, "not_a_type")
        with pytest.raises(KeyError):
            Notification.objects.bulk_create([Notification(recipient=user, notif_type="not_a_type")])


class TestPolicy:
    def test_inactive_recipient_receives_nothing(self):
        suspended = f.make_user(is_active=False)
        assert f.make_notification(suspended, "report_updated").pk is None

    def test_self_notification_is_dropped(self, user):
        assert f.make_notification(user, "follow", sender=user).pk is None

    @pytest.mark.parametrize("blocker_is_recipient", [True, False])
    def test_blocked_in_either_direction_cannot_notify(self, user, other_user, blocker_is_recipient):
        pair = (user, other_user) if blocker_is_recipient else (other_user, user)
        UserBlock.objects.create(blocker=pair[0], blocked=pair[1])
        assert f.make_notification(user, "follow", sender=other_user).pk is None

    def test_block_does_not_affect_other_senders_or_system_messages(self, user, other_user):
        UserBlock.objects.create(blocker=user, blocked=other_user)
        third = f.make_user(username=f.unique("third_"))
        assert f.make_notification(user, "follow", sender=third).pk is not None
        assert f.make_notification(user, "report_updated").pk is not None

    def test_batch_is_filtered_in_a_constant_number_of_queries(self, user, other_user, django_assert_max_num_queries):
        recipients = [f.make_user(username=f.unique("r_")) for _ in range(5)]
        with django_assert_max_num_queries(4):
            created = create_notifications("follow", recipients, sender=other_user)
        assert len(created) == 5


class TestNotify:
    def test_creates_one_per_recipient_and_broadcasts(self, user, other_user, monkeypatch):
        sent = []
        monkeypatch.setattr("app.services.notifications.broadcast_notifications", sent.extend)
        created = notify("follow", [user, other_user.pk], sender=f.make_user(username=f.unique("s_")))
        assert {n.recipient_id for n in created} == {user.pk, other_user.pk}
        assert sent == created

    def test_refused_notifications_are_not_broadcast(self, user, monkeypatch):
        sent = []
        monkeypatch.setattr("app.services.notifications.broadcast_notifications", sent.extend)
        muted = f.make_user(notif_follow=False)
        assert notify("follow", [muted], sender=user) == []
        assert sent == []
