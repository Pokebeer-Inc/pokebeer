import pytest
from django.urls import reverse

from app.models import BeerUser, Notification
from app.views.notification_views import FCM_TOKEN_MAX_LENGTH
from tests import factories as f
from tests.helpers import assert_redirects, post_json

pytestmark = pytest.mark.django_db


class TestReadNotification:
    @pytest.fixture
    def targets(self, other_user, beer, brewery, user):
        return {"sender": other_user, "beer": beer, "brewery": brewery, "report": f.make_report(user)}

    @pytest.mark.parametrize("notif_type, links, expected", [
        ("follow", ("sender",), lambda t: reverse("public_profile", args=[t["sender"].username])),
        ("beer_shared", ("beer",), lambda t: reverse("beer_detail", args=[t["beer"].slug])),
        ("drink_liked", ("beer",), lambda t: reverse("beer_detail", args=[t["beer"].slug])),
        ("beer_updated_by_manager", ("beer",), lambda t: reverse("beer_detail", args=[t["beer"].slug])),
        ("achievement", (), lambda t: reverse("achievements")),
        ("spot_invite", (), lambda t: reverse("map")),
        ("report_updated", ("report",), lambda t: reverse("my_reports")),
        ("feedback_replied", (), lambda t: reverse("account")),
        ("manager_added", ("brewery",), lambda t: reverse("brewery_detail", args=[t["brewery"].id])),
        ("beer_shared", (), lambda t: reverse("notifications")),
        ("manager_removed", (), lambda t: reverse("notifications")),
    ])
    def test_marks_read_and_redirects_to_the_target(self, auth_client, user, targets, notif_type, links, expected):
        notification = f.make_notification(user, notif_type, **{link: targets[link] for link in links})
        assert_redirects(auth_client.get(reverse("read_notification", args=[notification.id])), expected(targets))
        notification.refresh_from_db()
        assert notification.is_read

    def test_cannot_read_someone_else_notification(self, other_client, user):
        notification = f.make_notification(user)
        assert other_client.get(reverse("read_notification", args=[notification.id])).status_code == 404
        notification.refresh_from_db()
        assert not notification.is_read


class TestNotificationList:
    def test_lists_only_mine(self, auth_client, user, other_user):
        mine = f.make_notification(user)
        f.make_notification(other_user)
        assert list(auth_client.get(reverse("notifications")).context["notifications"]) == [mine]

    def test_delete_own(self, auth_client, user):
        notification = f.make_notification(user)
        assert_redirects(auth_client.post(reverse("delete_notification", args=[notification.id])), reverse("notifications"))
        assert not Notification.objects.exists()

    def test_cannot_delete_someone_else_notification(self, other_client, user):
        notification = f.make_notification(user)
        assert other_client.post(reverse("delete_notification", args=[notification.id])).status_code == 404
        assert Notification.objects.filter(pk=notification.pk).exists()


class TestUnreadApi:
    URL = reverse("api_unread_notifications")

    def test_returns_at_most_five_unread_of_mine_newest_first(self, auth_client, user, other_user):
        created = [f.make_notification(user, sender=other_user) for _ in range(6)]
        f.make_notification(user, is_read=True)
        f.make_notification(other_user)

        body = auth_client.get(self.URL).json()

        assert body["unread_count"] == 5
        assert [n["id"] for n in body["notifications"]] == [n.id for n in reversed(created)][:5]
        assert "bobby" in body["notifications"][0]["message"]

    @pytest.mark.parametrize("notif_type, toast", [
        ("report_updated", "warning"), ("spot_invite", "success"), ("manager_removed", "error"), ("follow", "info"),
    ])
    def test_toast_type(self, auth_client, user, notif_type, toast):
        f.make_notification(user, notif_type)
        assert auth_client.get(self.URL).json()["notifications"][0]["toastType"] == toast

    def test_achievement_includes_tier_and_icon(self, auth_client, user):
        for _ in range(5):
            f.make_drink(user)
        f.make_notification(user, "achievement", achievement_name="Juge", text_content="Juge (Bronze)")
        notification = auth_client.get(self.URL).json()["notifications"][0]
        assert notification["tier_slug"] == "bronze"
        assert notification["icon"]


class TestFcmToken:
    URL = reverse("api_update_fcm_token")

    def test_token_is_stored(self, auth_client, user):
        assert post_json(auth_client, self.URL, {"token": "abc"}).status_code == 200
        assert BeerUser.objects.get(pk=user.pk).fcm_token == "abc"

    @pytest.mark.parametrize("length", [255, 256, FCM_TOKEN_MAX_LENGTH])
    def test_long_tokens_are_stored_entirely(self, auth_client, user, length):
        assert post_json(auth_client, self.URL, {"token": "t" * length}).status_code == 200
        assert len(BeerUser.objects.get(pk=user.pk).fcm_token) == length

    @pytest.mark.parametrize("payload, raw", [
        ({}, None), ({"token": ""}, None), ({"token": "   "}, None), ({"token": 123}, None), ({"token": ["a"]}, None),
        ({"token": "t" * (FCM_TOKEN_MAX_LENGTH + 1)}, None), (None, "not-json"), (None, "[1]"),
    ])
    def test_invalid_payload_is_rejected(self, auth_client, user, payload, raw):
        assert post_json(auth_client, self.URL, payload, raw=raw).status_code == 400
        assert BeerUser.objects.get(pk=user.pk).fcm_token is None
