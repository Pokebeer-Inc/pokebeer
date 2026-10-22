"""Tirage du jour : rareté, tirage, un seul tirage par jour, rappel push."""
import random
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from app.domain import rarity
from app.models import DailyDraw, Notification
from app.services.catalog import daily_draw, draw_reminders
from app.services.members import achievements
from app.services.members.achievements import get_user_achievements
from tests import factories as f

pytestmark = pytest.mark.django_db

SIX_PM = timezone.now().astimezone(ZoneInfo('Europe/Paris')).replace(hour=18, minute=0, second=0, microsecond=0)


class TestRarity:
    def test_shares_and_weights_are_complete(self):
        assert sum(r.share for r in rarity.RARITIES) == pytest.approx(1)
        assert sum(r.weight for r in rarity.RARITIES) == 100

    @pytest.mark.parametrize("total", [0, 1, 3, 10, 57])
    def test_every_beer_gets_exactly_one_tier(self, total):
        tiers = rarity.split_ranking(list(range(total)))
        assert sorted(i for ids in tiers.values() for i in ids) == list(range(total))

    def test_the_most_tasted_beers_are_the_most_common(self):
        tiers = rarity.split_ranking(list(range(100)))  # classés de la plus goûtée à la moins goûtée
        assert tiers["common"] == list(range(40)) and tiers["legendary"] == list(range(90, 100))

    def test_a_legendary_beer_is_far_less_likely_than_a_common_one(self):
        per_beer = {r.key: r.weight / (r.share * 100) for r in rarity.RARITIES}
        assert per_beer["legendary"] < per_beer["epic"] < per_beer["rare"] < per_beer["common"]

    def test_empty_tiers_are_never_drawn(self):
        rng = random.Random(1)
        assert {rarity.pick_rarity(rng, {"rare"}).key for _ in range(50)} == {"rare"}

    def test_draw_frequencies_follow_the_weights(self):
        rng = random.Random(7)
        keys = [r.key for r in rarity.RARITIES]
        counts = Counter(rarity.pick_rarity(rng, set(keys)).key for _ in range(20000))
        for r in rarity.RARITIES:
            assert counts[r.key] / 20000 == pytest.approx(r.weight / 100, abs=0.015)


class TestPick:
    def tiers(self, total=20):
        return rarity.split_ranking(list(range(1, total + 1)))

    def test_five_distinct_beers_from_the_candidates_only(self):
        candidates = set(range(1, 21)) - {1, 2, 3}
        picks = daily_draw.pick(candidates, self.tiers(), random.Random(3))
        ids = [beer_id for beer_id, _ in picks]
        assert len(ids) == daily_draw.CARDS == len(set(ids)) and set(ids) <= candidates

    def test_each_card_carries_the_tier_of_its_beer(self):
        tiers = self.tiers()
        for beer_id, tier in daily_draw.pick(set(range(1, 21)), tiers, random.Random(5)):
            assert beer_id in tiers[tier]

    def test_cards_are_revealed_from_the_most_common_to_the_rarest(self):
        order = [r.key for r in rarity.RARITIES]
        for seed in range(20):
            found = [order.index(tier) for _, tier in daily_draw.pick(set(range(1, 21)), self.tiers(), random.Random(seed))]
            assert found == sorted(found)

    def test_fewer_cards_when_little_is_left(self):
        assert len(daily_draw.pick({4, 9}, self.tiers(), random.Random(0))) == 2
        assert daily_draw.pick(set(), self.tiers(), random.Random(0)) == []


class TestCatalogue:
    def test_rarity_follows_the_number_of_tastings(self):
        beers = [f.make_beer() for _ in range(10)]
        drinkers = [f.make_user() for _ in range(3)]
        for drinker in drinkers:
            f.make_drink(drinker, beers[0])  # la plus goûtée
        f.make_drink(drinkers[0], beers[1])
        tiers = daily_draw._tiers()
        assert beers[0].id in tiers["common"]
        assert all(beers[0].id not in ids for key, ids in tiers.items() if key != "common")
        assert beers[1].id not in tiers["legendary"]

    def test_deleted_beers_are_out_of_the_catalogue(self):
        gone = f.make_beer(is_deleted=True)
        keep = f.make_beer()
        ids = {i for ids in daily_draw._tiers().values() for i in ids}
        assert keep.id in ids and gone.id not in ids


class TestOpenToday:
    def catalogue(self, size=12):
        return [f.make_beer() for _ in range(size)]

    def test_never_offers_a_beer_already_tasted(self, user):
        beers = self.catalogue()
        tasted = beers[:4]
        for beer in tasted:
            f.make_drink(user, beer)
        draw = daily_draw.open_today(user)
        assert {c.beer_id for c in draw.cards.all()}.isdisjoint({b.id for b in tasted})

    def test_one_draw_per_day_the_second_call_returns_the_same_cards(self, user):
        self.catalogue()
        first = daily_draw.open_today(user)
        again = daily_draw.open_today(user)
        assert first.pk == again.pk and DailyDraw.objects.filter(user=user).count() == 1
        assert [c.beer_id for c in first.cards.all()] == [c.beer_id for c in again.cards.all()]

    def test_a_new_day_gives_a_new_draw(self, user):
        self.catalogue()
        draw = daily_draw.open_today(user)
        DailyDraw.objects.filter(pk=draw.pk).update(day=timezone.localdate() - timedelta(days=1))
        assert daily_draw.open_today(user).pk != draw.pk

    def test_previously_drawn_beers_may_come_back(self, user):
        self.catalogue(5)  # exactement cinq : les mêmes sortent forcément le lendemain
        first = daily_draw.open_today(user)
        DailyDraw.objects.filter(pk=first.pk).update(day=timezone.localdate() - timedelta(days=1))
        second = daily_draw.open_today(user)
        assert {c.beer_id for c in first.cards.all()} == {c.beer_id for c in second.cards.all()}

    def test_beers_of_blocked_members_are_never_offered(self, user, other_user):
        hidden = f.make_beer(added_by=other_user)
        self.catalogue(6)
        f.block(user, other_user)
        assert hidden.id not in {c.beer_id for c in daily_draw.open_today(user).cards.all()}

    def test_nothing_left_to_discover_creates_no_draw(self, user):
        f.make_drink(user, f.make_beer())
        assert daily_draw.open_today(user) is None
        assert not DailyDraw.objects.exists()

    def test_cards_are_only_the_members_own(self, user, other_user):
        self.catalogue()
        daily_draw.open_today(other_user)
        assert daily_draw.todays(user) is None


class TestHomeState:
    def test_state_follows_the_draw(self, user):
        f.make_beer()
        assert daily_draw.home_state(user) == daily_draw.AVAILABLE
        daily_draw.open_today(user)
        assert daily_draw.home_state(user) == daily_draw.IN_PROGRESS
        daily_draw.reveal(user, daily_draw.CARDS)
        assert daily_draw.home_state(user) == daily_draw.DONE

    def test_exhausted_when_everything_is_tasted(self, user):
        f.make_drink(user, f.make_beer())
        assert daily_draw.home_state(user) == daily_draw.EXHAUSTED

    def test_reveal_does_not_touch_other_members_or_days(self, user, other_user):
        f.make_beer()
        daily_draw.open_today(user)
        daily_draw.open_today(other_user)
        daily_draw.reveal(user, daily_draw.CARDS)
        assert DailyDraw.objects.get(user=other_user).completed_at is None


class TestReminders:
    def device(self, **fields):
        return f.make_user(fcm_token="token-" + f.unique("t"), **fields)

    def test_only_members_with_a_device_who_have_not_drawn_are_reminded(self):
        f.make_beer()
        due = self.device()
        drawn = self.device()
        daily_draw.open_today(drawn)
        f.make_user()  # sans appareil : la carte de l'accueil suffit
        suspended = self.device(is_active=False)
        assert draw_reminders.send_pending(SIX_PM) == 1
        assert Notification.objects.get().recipient_id == due.pk and not Notification.objects.filter(recipient=suspended).exists()

    def test_one_reminder_per_day(self):
        self.device()
        assert draw_reminders.send_pending(SIX_PM) == 1
        assert draw_reminders.send_pending(SIX_PM) == 0

    def test_a_new_reminder_replaces_the_unread_one(self):
        member = self.device()
        old = Notification.objects.create(recipient=member, notif_type=draw_reminders.TYPE)
        Notification.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=1))
        draw_reminders.send_pending(SIX_PM)
        assert Notification.objects.filter(recipient=member, notif_type=draw_reminders.TYPE).count() == 1
        assert not Notification.objects.filter(pk=old.pk).exists()

    def test_member_who_disabled_rewards_is_left_alone_without_looping(self):
        self.device(notif_achievements=False)
        assert draw_reminders.send_pending(SIX_PM) == 0

    @pytest.mark.parametrize("hour", [7, 17, 19])
    def test_nothing_is_sent_outside_six_pm_paris(self, hour):
        self.device()
        assert draw_reminders.send_pending(SIX_PM.replace(hour=hour)) == 0

    @pytest.mark.parametrize("utc_hour, month", [(16, 7), (17, 1)])
    def test_the_cron_hour_that_is_six_pm_in_paris_sends_in_summer_and_in_winter(self, utc_hour, month):
        self.device()
        moment = datetime(2026, month, 15, utc_hour, 0, tzinfo=ZoneInfo("UTC"))
        assert draw_reminders.send_pending(moment) == 1


@pytest.fixture
def one_draw_unlocks_bronze(monkeypatch):
    """Les paliers réels sont hauts : on abaisse celui de Bronze à un tirage pour tester le déblocage sans simuler des semaines de tirages."""
    lowered = tuple(replace(t, thresholds=(5, *t.thresholds[1:])) if t.slug == "decouvreur" else t for t in achievements.TROPHIES)
    monkeypatch.setattr(achievements, "TROPHIES", lowered)


class TestDiscovererTrophy:
    def trophy(self, user):
        achievements, _ = get_user_achievements(user)
        return next(a for a in achievements if a["slug"] == "decouvreur")

    def test_counts_every_card_turned_over(self, user, one_draw_unlocks_bronze):
        for _ in range(6):
            f.make_beer()
        daily_draw.open_today(user)
        assert self.trophy(user)["current"] == 0
        daily_draw.reveal(user, 2)
        assert self.trophy(user)["current"] == 2
        daily_draw.reveal(user, daily_draw.CARDS)
        assert self.trophy(user)["current"] == 5 and self.trophy(user)["tier_name"] == "Bronze"

    def test_completing_a_draw_notifies_the_tier(self, user, one_draw_unlocks_bronze):
        for _ in range(5):
            f.make_beer()
        daily_draw.open_today(user)
        daily_draw.reveal(user, daily_draw.CARDS)
        notification = Notification.objects.get(recipient=user, notif_type="achievement")
        assert notification.achievement_slug == "decouvreur" and notification.achievement_tier == 1

    def test_revealing_twice_counts_once(self, user):
        for _ in range(5):
            f.make_beer()
        daily_draw.open_today(user)
        daily_draw.reveal(user, daily_draw.CARDS)
        daily_draw.reveal(user, daily_draw.CARDS)
        assert self.trophy(user)["current"] == 5


class TestKillSwitch:
    def test_enabled_by_default_for_everyone(self, user):
        assert user.daily_draw_enabled is True

    def test_disabled_members_have_no_home_entry(self, user):
        f.make_beer()
        daily_draw.set_enabled(user, False)
        assert daily_draw.home_state(user) == daily_draw.DISABLED

    def test_disabled_members_get_no_reminder(self):
        member = f.make_user(fcm_token="token-x", daily_draw_enabled=False)
        assert draw_reminders.send_pending(SIX_PM) == 0 and not Notification.objects.filter(recipient=member).exists()

    def test_the_trophy_and_its_points_disappear_then_come_back(self, user, one_draw_unlocks_bronze):
        for _ in range(5):
            f.make_beer()
        daily_draw.open_today(user)
        daily_draw.reveal(user, daily_draw.CARDS)
        _, level_on = get_user_achievements(user)
        daily_draw.set_enabled(user, False)
        achievements, level_off = get_user_achievements(user)
        assert "decouvreur" not in {a["slug"] for a in achievements} and level_off["total_points"] < level_on["total_points"]
        daily_draw.set_enabled(user, True)
        achievements, level_back = get_user_achievements(user)
        assert level_back == level_on and "decouvreur" in {a["slug"] for a in achievements}

    def test_disabling_removes_the_related_notifications_only(self, user):
        reminder = f.make_notification(user, "daily_draw")
        trophy = f.make_notification(user, "achievement", achievement_slug="decouvreur", achievement_tier=1)
        other = f.make_notification(user, "achievement", achievement_slug="juge", achievement_tier=1)
        daily_draw.set_enabled(user, False)
        assert list(Notification.objects.filter(recipient=user)) == [other]
        assert not Notification.objects.filter(pk__in=[reminder.pk, trophy.pk]).exists()

    def test_no_trophy_notification_while_disabled(self, user):
        for _ in range(5):
            f.make_beer()
        daily_draw.open_today(user)
        daily_draw.set_enabled(user, False)
        daily_draw.reveal(user, daily_draw.CARDS)
        assert not Notification.objects.filter(recipient=user, notif_type="achievement").exists()

    def test_the_switch_is_idempotent(self, user):
        daily_draw.set_enabled(user, False)
        daily_draw.set_enabled(user, False)
        daily_draw.set_enabled(user, True)
        user.refresh_from_db()
        assert user.daily_draw_enabled is True


class TestProgress:
    def draw(self, user, size=6):
        for _ in range(size):
            f.make_beer()
        return daily_draw.open_today(user)

    def test_a_new_draw_starts_with_nothing_revealed(self, user):
        assert self.draw(user).revealed == 0

    def test_progress_is_kept_and_never_goes_back(self, user):
        self.draw(user)
        assert daily_draw.reveal(user, 3) == 3
        assert daily_draw.reveal(user, 1) == 3  # une requête en retard ne fait pas reculer
        assert daily_draw.todays(user).revealed == 3

    def test_the_draw_is_complete_once_every_card_is_revealed(self, user):
        self.draw(user)
        daily_draw.reveal(user, 4)
        assert daily_draw.home_state(user) == daily_draw.IN_PROGRESS
        daily_draw.reveal(user, 5)
        assert daily_draw.home_state(user) == daily_draw.DONE

    def test_the_count_is_clamped_to_the_cards_of_the_draw(self, user):
        self.draw(user)
        assert daily_draw.reveal(user, 99) == daily_draw.CARDS
        assert daily_draw.reveal(user, -3) == daily_draw.CARDS

    def test_a_short_draw_completes_with_fewer_cards(self, user):
        self.draw(user, size=2)
        daily_draw.reveal(user, 2)
        assert daily_draw.home_state(user) == daily_draw.DONE

    def test_no_draw_means_nothing_to_reveal(self, user):
        assert daily_draw.reveal(user, 1) is None
