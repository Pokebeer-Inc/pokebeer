from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import Beer, Drinks
from app.views.services.recommendations import get_recommended_beers
from app.views.services.stats import get_top_beers_data, get_user_statistics
from tests import factories as f

pytestmark = pytest.mark.django_db


def drinks_of(user):
    return Drinks.objects.filter(drinker_id=user)


def unrated_for(user):
    return Beer.objects.filter(is_deleted=False).exclude(drinks__drinker_id=user)


class TestUserStatistics:
    def test_empty_history(self, user):
        assert get_user_statistics(drinks_of(user)) == {
            "total_drinks": 0, "drinks_last_month": 0, "avg_note": 0, "avg_abv": 0, "avg_ibu": 0,
            "pref_style": "Pas encore défini",
        }

    def test_averages(self, user):
        f.make_drink(user, f.make_beer(degree=Decimal("4.0"), bitterness=10), note=8)
        f.make_drink(user, f.make_beer(degree=Decimal("6.0"), bitterness=30), note=6)
        stats = get_user_statistics(drinks_of(user))
        assert (stats["total_drinks"], stats["avg_note"], stats["avg_abv"], stats["avg_ibu"]) == (2, 7, 5, 20)

    def test_drinks_on_deleted_beers_are_ignored(self, user):
        f.make_drink(user, f.make_beer(is_deleted=True), note=10)
        assert get_user_statistics(drinks_of(user))["total_drinks"] == 0

    @pytest.mark.parametrize("days_ago, counted", [(0, True), (30, True), (31, False)])
    def test_last_month_window_is_30_days(self, user, days_ago, counted):
        f.make_drink(user, date=date.today() - timedelta(days=days_ago))
        assert get_user_statistics(drinks_of(user))["drinks_last_month"] == int(counted)

    def test_preferred_style_splits_multi_styles_and_ignores_disliked_beers(self, user):
        f.make_drink(user, f.make_beer(style="Stout, IPA"), note=7)
        f.make_drink(user, f.make_beer(style="IPA"), note=9)
        f.make_drink(user, f.make_beer(style="Lager"), note=6)
        f.make_drink(user, f.make_beer(style="Lager"), note=6)
        assert get_user_statistics(drinks_of(user))["pref_style"] == "IPA"


class TestTopBeers:
    def test_empty_slots_are_kept_only_when_requested(self, user, beer):
        f.make_drink(user, beer, note=9)
        user.top_beer_2 = beer
        user.save()

        with_empty = get_top_beers_data(user, drinks_of(user), include_empty=True)
        without_empty = get_top_beers_data(user, drinks_of(user), include_empty=False)

        assert [(slot["slot"], slot["beer"], slot["note"]) for slot in with_empty] == [(1, None, None), (2, beer, 9), (3, None, None)]
        assert [slot["slot"] for slot in without_empty] == [2]

    def test_note_is_none_for_a_top_beer_never_rated(self, user, beer):
        user.top_beer_1 = beer
        assert get_top_beers_data(user, drinks_of(user))[0]["note"] is None


class TestRecommendations:
    def test_without_liked_beers_falls_back_to_best_rated(self, user, other_user):
        best, average = f.make_beer(name="Best"), f.make_beer(name="Average")
        f.make_beer(name="Never rated")
        f.make_drink(other_user, best, note=10)
        f.make_drink(other_user, average, note=5)
        assert [b.name for b in get_recommended_beers(drinks_of(user), unrated_for(user))] == ["Best", "Average"]

    def test_liked_style_and_brewery_rank_first(self, user, other_user):
        favourite = f.make_brewery(name="Favourite")
        f.make_drink(user, f.make_beer(style="IPA", brewery=favourite, degree=Decimal("6.0"), bitterness=60), note=9)
        f.make_beer(name="Other stout", style="Stout", degree=Decimal("12.0"), bitterness=5)
        f.make_beer(name="Same brewery IPA", style="Session IPA", brewery=favourite, degree=Decimal("6.5"), bitterness=55)

        recommended = get_recommended_beers(drinks_of(user), unrated_for(user))

        assert [b.name for b in recommended] == ["Same brewery IPA"]
        assert recommended[0].match_score == 7

    def test_at_most_five_recommendations(self, user, other_user):
        for _ in range(7):
            f.make_drink(other_user, f.make_beer(), note=8)
        assert len(get_recommended_beers(drinks_of(user), unrated_for(user))) == 5

    def test_empty_catalogue_returns_no_recommendation(self, user):
        assert list(get_recommended_beers(drinks_of(user), unrated_for(user))) == []
