from unittest import mock

import pytest

from app.models import Notification
from app.services import realtime_service
from app.services.security import get_secure_channel_name
from tests import factories as f

pytestmark = pytest.mark.django_db


@pytest.fixture
def supabase(settings, monkeypatch):
    settings.SUPABASE_URL = "https://project.supabase.co"
    settings.SUPABASE_SERVICE_ROLE_KEY = "service-key"
    post = mock.Mock(return_value=mock.Mock(status_code=200))
    monkeypatch.setattr(realtime_service.requests, "post", post)
    return post


@pytest.fixture
def firebase(monkeypatch):
    send = mock.Mock()
    monkeypatch.setattr(realtime_service.firebase_admin, "_apps", {"[DEFAULT]": object()})
    monkeypatch.setattr(realtime_service.messaging, "send", send)
    return send


def sent_messages(post):
    return post.call_args.kwargs["json"]["messages"]


class TestBroadcastGuards:
    def test_nothing_is_sent_without_supabase_configuration(self, user, monkeypatch):
        post = mock.Mock()
        monkeypatch.setattr(realtime_service.requests, "post", post)
        realtime_service.broadcast_notifications([f.make_notification(user)])
        post.assert_not_called()

    def test_empty_list_is_a_no_op(self, supabase):
        realtime_service.broadcast_notifications([])
        supabase.assert_not_called()

    def test_unsaved_notifications_are_skipped(self, supabase, user):
        realtime_service.broadcast_notifications([Notification(recipient=user, notif_type="follow")])
        assert sent_messages(supabase) == []


class TestBroadcastPayload:
    def test_single_request_on_private_channel(self, supabase, user, other_user):
        notifications = [f.make_notification(user, sender=other_user), f.make_notification(other_user, sender=user)]

        realtime_service.broadcast_notifications(notifications)

        supabase.assert_called_once()
        messages = sent_messages(supabase)
        assert [m["topic"] for m in messages] == [get_secure_channel_name(user.id), get_secure_channel_name(other_user.id)]
        assert messages[0]["event"] == "new_notification"
        assert messages[0]["payload"]["read_url"] == f"/notifications/read/{notifications[0].slug}/"
        assert messages[0]["payload"]["slug"] == notifications[0].slug and "id" not in messages[0]["payload"]
        assert "bobby" in messages[0]["payload"]["message"]

    def test_request_is_authenticated_and_time_boxed(self, supabase, user):
        realtime_service.broadcast_notifications([f.make_notification(user)])
        call = supabase.call_args
        assert call.args[0] == "https://project.supabase.co/realtime/v1/api/broadcast"
        assert call.kwargs["headers"]["Authorization"] == "Bearer service-key"
        assert sum(call.kwargs["timeout"]) <= 2

    @pytest.mark.parametrize("notif_type, toast", [("report_updated", "warning"), ("beer_added", "success"), ("follow", "info")])
    def test_toast_type_depends_on_notification_type(self, supabase, user, notif_type, toast):
        realtime_service.broadcast_notifications([f.make_notification(user, notif_type)])
        assert sent_messages(supabase)[0]["payload"]["toastType"] == toast

    @pytest.mark.parametrize("failure", [ConnectionError("down"), None])
    def test_supabase_failures_are_swallowed(self, supabase, user, failure):
        supabase.side_effect = failure
        supabase.return_value = mock.Mock(status_code=500, text="boom")
        realtime_service.broadcast_notifications([f.make_notification(user)])

    def test_achievement_notification_carries_tier_and_icon(self, supabase, user):
        for _ in range(5):
            f.make_drink(user)
        notification = f.make_notification(user, "achievement", achievement_name="Juge", text_content="Juge (Bronze)")
        realtime_service.broadcast_notifications([notification])
        payload = sent_messages(supabase)[0]["payload"]
        assert payload["tier_slug"] == "bronze" and payload["icon"]

    def test_each_recipient_gets_his_own_achievement_tier(self, supabase, user, other_user):
        for _ in range(10):
            f.make_drink(user)
        for _ in range(5):
            f.make_drink(other_user)
        realtime_service.broadcast_notifications([
            f.make_notification(recipient, "achievement", achievement_name="Juge", text_content="Juge")
            for recipient in (user, other_user)
        ])
        assert [m["payload"]["tier_slug"] for m in sent_messages(supabase)] == ["silver", "bronze"]

    def test_unknown_achievement_has_no_tier(self, supabase, user):
        realtime_service.broadcast_notifications([f.make_notification(user, "achievement", achievement_name="Inconnu", text_content="?")])
        assert sent_messages(supabase)[0]["payload"]["tier_slug"] is None

    def test_earning_an_achievement_through_the_app_does_not_crash(self, supabase, user):
        from app.views.utils import check_and_notify_achievements
        for _ in range(5):
            f.make_drink(user)
        check_and_notify_achievements(user)
        assert any(m["payload"]["tier_slug"] for m in sent_messages(supabase))


class TestFirebasePush:
    def test_push_is_sent_to_devices_with_a_token(self, supabase, firebase, other_user):
        recipient = f.make_user(fcm_token="device-token")
        realtime_service.broadcast_notifications([f.make_notification(recipient, sender=other_user)])
        message = firebase.call_args.args[0]
        assert message.token == "device-token"
        assert "<" not in message.notification.body and "bobby" in message.notification.body

    def test_push_carries_the_relative_read_url_for_deep_linking(self, supabase, firebase, other_user):
        recipient = f.make_user(fcm_token="device-token")
        notification = f.make_notification(recipient, sender=other_user)
        realtime_service.broadcast_notifications([notification])
        assert firebase.call_args.args[0].data == {"read_url": f"/notifications/read/{notification.slug}/"}

    def test_no_push_without_token(self, supabase, firebase, user):
        realtime_service.broadcast_notifications([f.make_notification(user)])
        firebase.assert_not_called()

    def test_push_is_sent_even_without_supabase(self, firebase, monkeypatch):
        post = mock.Mock()
        monkeypatch.setattr(realtime_service.requests, "post", post)
        realtime_service.broadcast_notifications([f.make_notification(f.make_user(fcm_token="device-token"))])
        assert firebase.call_args.args[0].token == "device-token"
        post.assert_not_called()

    def test_push_failure_does_not_prevent_websocket_broadcast(self, supabase, firebase):
        firebase.side_effect = RuntimeError("fcm down")
        realtime_service.broadcast_notifications([f.make_notification(f.make_user(fcm_token="t"))])
        supabase.assert_called_once()
