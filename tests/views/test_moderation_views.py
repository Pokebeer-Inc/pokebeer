from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from app.models import Report, UserBlock, UserFollow
from tests import factories as f
from tests.helpers import assert_redirects, messages_of

pytestmark = pytest.mark.django_db

DESCRIPTION = "Publicité déguisée pour un site"


class TestSubmitReport:
    URL = reverse("submit_report")

    def report(self, client, item_type, item_id, referer=None, **overrides):
        data = {"item_type": item_type, "item_id": item_id, "reason": "spam", "description": DESCRIPTION, **overrides}
        extra = {"HTTP_REFERER": referer} if referer else {}
        return client.post(self.URL, data, **extra)

    @pytest.mark.parametrize("item_type, field", [
        ("beer", "reported_beer"), ("drink", "reported_drink"), ("user", "reported_user"), ("brewery", "reported_brewery"),
    ])
    def test_report_targets_the_requested_item(self, auth_client, user, other_user, beer, item_type, field):
        target = {"beer": beer, "drink": f.make_drink(other_user, beer), "user": other_user, "brewery": beer.brewery_id}[item_type]
        self.report(auth_client, item_type, target.id)
        report = Report.objects.get()
        assert (report.reporter, getattr(report, field), report.status) == (user, target, "pending")

    def test_description_is_trimmed(self, auth_client, beer):
        self.report(auth_client, "beer", beer.id, description=f"   {DESCRIPTION}   ")
        assert Report.objects.get().description == DESCRIPTION

    @pytest.mark.parametrize("referer, expected", [("/user/bobby/", "/user/bobby/?reported=1"), ("/user/bobby/?tab=x", "/user/bobby/?tab=x&reported=1")])
    def test_user_report_flags_the_return_url(self, auth_client, other_user, referer, expected):
        assert_redirects(self.report(auth_client, "user", other_user.id, referer=referer), expected)

    def test_beer_report_returns_to_referer(self, auth_client, beer):
        assert_redirects(self.report(auth_client, "beer", beer.id, referer="/beers/"), "/beers/")

    def test_my_reports_lists_only_mine(self, auth_client, user, other_user):
        mine = f.make_report(user)
        f.make_report(other_user)
        assert list(auth_client.get(reverse("my_reports")).context["reports"]) == [mine]

    @pytest.mark.parametrize("overrides, label", [
        ({"description": ""}, "Description"),
        ({"description": "          "}, "Description"),
        ({"description": "x" * 9}, "Description"),
        ({"description": "x" * 1001}, "Description"),
        ({"reason": "hack"}, "Raison"),
        ({"reason": ""}, "Raison"),
        ({"item_type": "planet"}, "Élément signalé"),
        ({"item_type": ""}, "Élément signalé"),
        ({"item_id": "abc"}, "Élément signalé"),
        ({"item_id": "0"}, "Élément signalé"),
        ({"item_id": "999999"}, "Élément signalé"),
    ], ids=[
        "empty-description", "blank-description", "description-too-short", "description-too-long", "unknown-reason",
        "no-reason", "unknown-target", "no-target", "non-numeric-id", "zero-id", "missing-item",
    ])
    def test_invalid_report_is_rejected_with_an_explanation(self, auth_client, beer, overrides, label):
        data = {"item_type": "beer", "item_id": beer.id, **overrides}
        response = self.report(auth_client, data.pop("item_type"), data.pop("item_id"), referer="/beers/", **data)
        assert_redirects(response, "/beers/")
        assert not Report.objects.exists()
        assert any(m.startswith("Votre signalement n'a pas pu être envoyé") and f"{label} :" in m for m in messages_of(response))

    @pytest.mark.parametrize("length", [10, 1000])
    def test_description_length_limits_are_inclusive(self, auth_client, beer, length):
        self.report(auth_client, "beer", beer.id, description="x" * length)
        assert Report.objects.count() == 1

    def test_cannot_report_oneself(self, auth_client, user):
        response = self.report(auth_client, "user", user.id)
        assert not Report.objects.exists()
        assert any("propre profil" in m for m in messages_of(response))

    def test_cannot_report_own_tasting(self, auth_client, user):
        self.report(auth_client, "drink", f.make_drink(user).id)
        assert not Report.objects.exists()

    def test_own_beer_can_still_be_reported(self, auth_client, user):
        self.report(auth_client, "beer", f.make_beer(added_by=user).id)
        assert Report.objects.count() == 1

    def test_daily_limit(self, auth_client, user, beer, settings):
        settings.REPORT_DAILY_LIMIT = 3
        for _ in range(4):
            response = self.report(auth_client, "beer", beer.id)
        assert Report.objects.filter(reporter=user).count() == 3
        assert any("limite de 3 signalements" in m for m in messages_of(response))

    def test_daily_limit_counts_only_the_last_24_hours(self, auth_client, user, beer, settings):
        settings.REPORT_DAILY_LIMIT = 1
        old = f.make_report(user)
        Report.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=25))
        self.report(auth_client, "beer", beer.id)
        assert Report.objects.filter(reporter=user).count() == 2

    def test_daily_limit_is_per_user(self, auth_client, user, other_user, beer, settings):
        settings.REPORT_DAILY_LIMIT = 1
        f.make_report(other_user)
        self.report(auth_client, "beer", beer.id)
        assert Report.objects.filter(reporter=user).count() == 1

    def test_default_daily_limit_is_ten(self):
        from pokebeer import settings as project_settings
        assert project_settings.REPORT_DAILY_LIMIT == 10

    @pytest.mark.parametrize("referer", ["https://evil.example/", "//evil.example/", "javascript:alert(1)"])
    def test_never_redirects_to_another_site(self, auth_client, beer, referer):
        assert_redirects(self.report(auth_client, "beer", beer.id, referer=referer), reverse("index"))


class TestBlocking:
    def test_block_removes_mutual_follows(self, auth_client, user, other_user):
        f.follow(user, other_user)
        f.follow(other_user, user)
        assert_redirects(auth_client.post(reverse("block_user", args=[other_user.username])), reverse("index"))
        assert UserBlock.objects.filter(blocker=user, blocked=other_user).exists()
        assert not UserFollow.objects.exists()

    def test_block_is_idempotent(self, auth_client, other_user):
        for _ in range(2):
            auth_client.post(reverse("block_user", args=[other_user.username]))
        assert UserBlock.objects.count() == 1

    def test_cannot_block_oneself(self, auth_client):
        auth_client.post(reverse("block_user", args=["alice"]))
        assert not UserBlock.objects.exists()

    def test_unblock_only_removes_my_block(self, auth_client, user, other_user):
        f.block(user, other_user)
        f.block(other_user, user)
        auth_client.post(reverse("unblock_user", args=[other_user.username]))
        assert list(UserBlock.objects.values_list("blocker__username", flat=True)) == ["bobby"]

    def test_blocked_list_shows_only_my_blocks(self, auth_client, user, other_user):
        mine = f.block(user, other_user)
        f.block(other_user, user)
        assert list(auth_client.get(reverse("blocked_users")).context["blocked_list"]) == [mine]

    @pytest.mark.parametrize("name", ["block_user", "unblock_user"])
    def test_unknown_user_is_404(self, auth_client, name):
        assert auth_client.post(reverse(name, args=["ghost"])).status_code == 404
