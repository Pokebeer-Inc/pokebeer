import pytest
from django.urls import reverse

from app.models import Drinks, Notification
from tests import factories as f
from tests.helpers import assert_redirects

pytestmark = pytest.mark.django_db


def rating(note="8", **overrides):
    return {"date": "2026-02-01", "note": note, "comment": "Bonne mousse", **overrides}


class TestRateBeer:
    def rate(self, client, beer, **data):
        return client.post(reverse("rate_beer", args=[beer.slug]), rating(**data), HTTP_REFERER="/beers/")

    def test_rating_is_saved_and_returns_to_referer(self, auth_client, user, beer):
        assert_redirects(self.rate(auth_client, beer), "/beers/")
        assert Drinks.objects.get(drinker_id=user, beer_id=beer).note == 8

    def test_second_rating_is_refused(self, auth_client, user, beer):
        self.rate(auth_client, beer)
        self.rate(auth_client, beer, note="2")
        assert list(Drinks.objects.values_list("note", flat=True)) == [8]

    def test_rated_beer_leaves_the_wishlist(self, auth_client, user, beer):
        user.wishlist_beers.add(beer)
        self.rate(auth_client, beer)
        assert not user.wishlist_beers.exists()

    def test_previous_tasters_are_notified(self, auth_client, other_user, beer):
        f.make_drink(other_user, beer)
        self.rate(auth_client, beer)
        assert list(Notification.objects.values_list("recipient", "notif_type")) == [(other_user.id, "beer_shared")]

    def test_only_own_notebooks_are_used(self, auth_client, user, other_user, beer):
        mine, foreign = f.make_notebook(user), f.make_notebook(other_user)
        self.rate(auth_client, beer, notebooks=[mine.slug, foreign.slug])
        assert list(Drinks.objects.get().notebooks.all()) == [mine]

    @pytest.mark.parametrize("note", ["0", "10", ""])
    def test_limit_notes_are_accepted(self, auth_client, beer, note):
        self.rate(auth_client, beer, note=note)
        assert Drinks.objects.exists()

    @pytest.mark.parametrize("note", ["11", "-1", "abc"])
    def test_invalid_notes_are_refused(self, auth_client, beer, note):
        self.rate(auth_client, beer, note=note)
        assert not Drinks.objects.exists()

    def test_get_does_not_rate(self, auth_client, beer):
        auth_client.get(reverse("rate_beer", args=[beer.slug]))
        assert not Drinks.objects.exists()

    def test_unknown_beer_is_404(self, auth_client):
        assert auth_client.post(reverse("rate_beer", args=["unknown-slug"]), rating()).status_code == 404


class TestModifyRating:
    def test_owner_updates_rating_and_notebooks(self, auth_client, user, beer):
        old, new = f.make_notebook(user), f.make_notebook(user)
        drink = f.make_drink(user, beer, note=3)
        old.drinks.add(drink)

        response = auth_client.post(reverse("modify_rate_beer", args=[drink.slug]), rating(note="9", notebooks=[new.slug]))

        assert_redirects(response, reverse("beer_detail", args=[beer.slug]))
        drink.refresh_from_db()
        assert drink.note == 9
        assert list(drink.notebooks.all()) == [new]

    def test_foreign_notebooks_of_the_drink_are_left_untouched(self, auth_client, user, other_user, beer):
        drink = f.make_drink(user, beer)
        foreign = f.make_notebook(other_user, drinks=[drink])
        auth_client.post(reverse("modify_rate_beer", args=[drink.slug]), rating())
        assert list(drink.notebooks.all()) == [foreign]

    def test_cannot_modify_someone_else_rating(self, other_client, user, beer):
        drink = f.make_drink(user, beer, note=3)
        assert other_client.post(reverse("modify_rate_beer", args=[drink.slug]), rating(note="10")).status_code == 404
        drink.refresh_from_db()
        assert drink.note == 3


class TestDeleteDrink:
    def test_owner_deletes_and_top_beer_is_cleared(self, auth_client, user, beer):
        drink = f.make_drink(user, beer)
        user.top_beer_1 = user.top_beer_3 = beer
        user.save()

        auth_client.post(reverse("delete_drink", args=[drink.slug]))

        user.refresh_from_db()
        assert not Drinks.objects.exists()
        assert (user.top_beer_1, user.top_beer_3) == (None, None)

    def test_get_does_not_delete(self, auth_client, user, beer):
        drink = f.make_drink(user, beer)
        auth_client.get(reverse("delete_drink", args=[drink.slug]))
        assert Drinks.objects.filter(pk=drink.pk).exists()

    def test_cannot_delete_someone_else_drink(self, other_client, user, beer):
        drink = f.make_drink(user, beer)
        assert other_client.post(reverse("delete_drink", args=[drink.slug])).status_code == 404
        assert Drinks.objects.filter(pk=drink.pk).exists()
