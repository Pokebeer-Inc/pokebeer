import pytest
from django.contrib.auth.models import AnonymousUser

from app.models import Notification, UserAchievementState
from app.views.utils import (
    TIER_NAMES, check_and_notify_achievements, get_excluded_users, get_user_achievements,
)
from tests import factories as f

pytestmark = pytest.mark.django_db


def achievement(user, slug):
    achievements, _ = get_user_achievements(user)
    return next(a for a in achievements if a["slug"] == slug)


def drink_many(user, count, **fields):
    return [f.make_drink(user, **fields) for _ in range(count)]


class TestAchievementTiers:
    def test_fresh_user_has_nothing_unlocked(self, user):
        achievements, level = get_user_achievements(user)
        assert all(a["tier_level"] == 0 and a["tier_name"] == TIER_NAMES[0] for a in achievements)
        assert level == {
            "total_points": 0, "current_level": 1, "points_in_current_level": 0,
            "points_required_for_next_level": 600, "progress_percentage": 0,
        }

    def test_progress_just_below_first_threshold(self, user):
        drink_many(user, 4)
        juge = achievement(user, "juge")
        assert (juge["tier_level"], juge["current"], juge["target"], juge["progress"]) == (0, 4, 5, 80)

    def test_first_threshold_unlocks_bronze(self, user):
        drink_many(user, 5)
        juge = achievement(user, "juge")
        assert (juge["tier_slug"], juge["target"], juge["next_tier_xp"]) == ("bronze", 10, 1000)

    @pytest.mark.parametrize("note, counted", [(0, True), (1, True), (2, False)])
    def test_bad_trip_counts_only_notes_strictly_below_two(self, user, note, counted):
        drink_many(user, 5, note=note)
        assert achievement(user, "bad_trip")["tier_level"] == int(counted)

    def test_hidden_achievement_description_is_masked_until_unlocked(self, user):
        assert achievement(user, "picon")["desc"].startswith("Défi caché")
        user.bio = "J'adore le PICON bière"
        user.save()
        picon = achievement(user, "picon")
        assert picon["is_maxed"] and picon["progress"] == 100
        assert "Picon" in picon["desc"]

    @pytest.mark.parametrize("note, tier", [(4, 0), (5, 1), (6, 2), (8, 3), (10, 4)])
    def test_irish_achievement_uses_best_guinness_note(self, user, note, tier):
        f.make_drink(user, f.make_beer(name=f.unique("Guinness Draught ")), note=note)
        assert achievement(user, "irlandais")["tier_level"] == tier

    def test_brewery_achievement_links_to_the_brewery(self, user):
        ours = f.make_brewery(name="Brasserie de l'Ours Doré")
        f.make_drink(user, f.make_beer(brewery=ours))
        ach = achievement(user, "ours")
        assert ach["is_maxed"]
        assert ach["url"] == f"/brewery/{ours.id}/"

    def test_deleted_beers_do_not_count_as_additions(self, user):
        f.make_beer(added_by=user, is_deleted=True)
        assert achievement(user, "poche")["tier_level"] == 0


class TestLevels:
    def test_points_roll_over_into_next_level(self, user):
        drink_many(user, 5)
        _, level = get_user_achievements(user)
        # 5 notes x 100 pts + médaille bronze "Juge" 500 pts = 1000 pts -> niveau 2 (600) + 400/800
        assert level == {
            "total_points": 1000, "current_level": 2, "points_in_current_level": 400,
            "points_required_for_next_level": 800, "progress_percentage": 50,
        }


class TestAchievementNotifications:
    def test_unlock_notifies_once(self, user):
        drink_many(user, 5)
        check_and_notify_achievements(user)
        check_and_notify_achievements(user)
        assert list(Notification.objects.values_list("text_content", flat=True)) == ["Juge (Bronze)"]
        assert UserAchievementState.objects.get(user=user, achievement_name="Juge").tier_level == 1

    def test_lost_tier_removes_its_notification(self, user):
        drinks = drink_many(user, 5)
        check_and_notify_achievements(user)
        drinks[0].delete()
        check_and_notify_achievements(user)
        assert not Notification.objects.filter(notif_type="achievement").exists()
        assert UserAchievementState.objects.get(user=user, achievement_name="Juge").tier_level == 0

    def test_opted_out_user_gets_state_but_no_notification(self):
        member = f.make_user(notif_achievements=False)
        drink_many(member, 5)
        check_and_notify_achievements(member)
        assert not Notification.objects.exists()
        assert UserAchievementState.objects.filter(user=member, tier_level=1).exists()

    def test_anonymous_user_is_ignored(self):
        assert check_and_notify_achievements(AnonymousUser()) is None
        assert not UserAchievementState.objects.exists()


class TestExcludedUsers:
    def test_block_is_symmetric(self, user, other_user):
        f.block(user, other_user)
        assert get_excluded_users(user) == [other_user.id]
        assert get_excluded_users(other_user) == [user.id]

    def test_anonymous_excludes_nobody(self):
        assert get_excluded_users(AnonymousUser()) == []
