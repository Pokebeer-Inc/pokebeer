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

    def test_rating_is_saved_and_leads_to_the_thank_you_page_that_returns_to_the_referer(self, auth_client, user, beer):
        assert_redirects(self.rate(auth_client, beer), reverse("rate_beer_done", args=[beer.slug]))
        assert Drinks.objects.get(drinker=user, beer=beer).note == 8
        page = auth_client.get(reverse("rate_beer_done", args=[beer.slug])).content.decode()
        assert 'href="/beers/"' in page and "Merci" in page and beer.name in page and "8/10" in page

    def test_a_refused_rating_goes_back_without_celebrating(self, auth_client, beer):
        assert_redirects(self.rate(auth_client, beer, note="11"), "/beers/")

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


class TestRateBeerDone:
    def test_the_page_celebrates_the_members_own_rating(self, auth_client, user, beer):
        f.make_drink(user, beer, note=9)
        response = auth_client.get(reverse("rate_beer_done", args=[beer.slug]))
        html = response.content.decode()
        assert response.status_code == 200 and "celebration-glass" in html and 'id="confetti"' in html and "script/celebration.js" in html
        assert "Votre toute première dégustation" in html and "9/10" in html

    def test_the_count_of_tastings_is_shown(self, auth_client, user, beer):
        f.make_drink(user, f.make_beer())
        f.make_drink(user, beer)
        assert "2 dégustations" in auth_client.get(reverse("rate_beer_done", args=[beer.slug])).content.decode()

    def test_a_beer_the_member_did_not_rate_is_a_404(self, auth_client, other_user, beer):
        f.make_drink(other_user, beer)
        assert auth_client.get(reverse("rate_beer_done", args=[beer.slug])).status_code == 404

    def test_a_removed_beer_is_a_404(self, auth_client, user):
        removed = f.make_beer(is_deleted=True)
        f.make_drink(user, removed)
        assert auth_client.get(reverse("rate_beer_done", args=[removed.slug])).status_code == 404

    def test_without_a_remembered_page_the_back_link_is_the_beer_page(self, auth_client, user, beer):
        f.make_drink(user, beer)
        assert f'href="{reverse("beer_detail", args=[beer.slug])}"' in auth_client.get(reverse("rate_beer_done", args=[beer.slug])).content.decode()

    @pytest.mark.parametrize("referer", ["https://evil.test/phish", "//evil.test", "javascript:alert(1)"])
    def test_a_foreign_referer_is_never_offered_as_a_way_back(self, auth_client, beer, referer):
        auth_client.post(reverse("rate_beer", args=[beer.slug]), rating(), HTTP_REFERER=referer)
        page = auth_client.get(reverse("rate_beer_done", args=[beer.slug])).content.decode()
        assert "evil.test" not in page and "javascript:alert" not in page and f'href="{reverse("index")}"' in page

    def test_anonymous_visitors_are_sent_to_login(self, client, beer):
        assert client.get(reverse("rate_beer_done", args=[beer.slug])).status_code == 302

