"""Un compte suspendu disparaît des vues sociales, sans casser le catalogue partagé."""
import pytest
from django.urls import reverse

from app.models import BeerSpot, BeerUser, UserFollow
from tests import factories as f

pytestmark = pytest.mark.django_db


@pytest.fixture
def suspended(db):
    return f.make_user(username="banned", is_active=False)


def test_public_profile_is_not_found(auth_client, suspended):
    assert auth_client.get(reverse("public_profile", args=[suspended.username])).status_code == 404


@pytest.mark.parametrize("item_type", ["public_drinks", "public_added_beers"])
def test_profile_lists_cannot_be_loaded(auth_client, suspended, item_type):
    url = reverse("load_more_generic", args=[item_type])
    assert auth_client.get(url, {"username": suspended.username}).status_code == 404


def test_cannot_be_followed(auth_client, user, suspended):
    assert auth_client.post(reverse("follow_user", args=[suspended.username])).status_code == 404
    assert not UserFollow.objects.filter(follower=user).exists()


def test_is_hidden_from_user_search(auth_client, suspended):
    f.make_user(username="banana")
    response = auth_client.get(reverse("load_more_generic", args=["search_users"]), {"uq": "ban"})
    assert "banana" in response.json()["html"] and "banned" not in response.json()["html"]


def test_tastings_are_hidden_on_the_beer_page(auth_client, other_user, suspended, beer):
    visible = f.make_drink(other_user, beer)
    f.make_drink(suspended, beer)
    response = auth_client.get(reverse("beer_detail", args=[beer.slug]))
    assert [drink.pk for drink in response.context["drinks"]] == [visible.pk]


def test_added_beers_stay_in_the_shared_catalogue(auth_client, suspended):
    kept = f.make_beer(name="Bière du banni", added_by=suspended)
    response = auth_client.get(reverse("load_more_generic", args=["search_beers"]), {"q": "banni"})
    assert kept.name in response.json()["html"]


def test_spots_created_by_a_suspended_user_leave_the_map(auth_client, user, suspended):
    f.make_spot(suspended, friends=[user])
    assert list(auth_client.get(reverse("map")).context["user_spots"]) == []


class TestFollowLists:
    def test_hidden_from_my_followers_and_following(self, auth_client, user, suspended):
        f.follow(suspended, user)
        f.follow(user, suspended)
        context = auth_client.get(reverse("account")).context
        assert (list(context["followers"]), list(context["following"])) == ([], [])

    def test_hidden_from_someone_else_profile(self, auth_client, other_user, suspended):
        f.follow(suspended, other_user)
        context = auth_client.get(reverse("public_profile", args=[other_user.username])).context
        assert list(context["followers"]) == []

    def test_not_offered_as_spot_friend(self, auth_client, user, suspended):
        f.follow(suspended, user)
        assert list(auth_client.get(reverse("map")).context["followers"]) == []


class TestSpotInvitations:
    def create_spot(self, client, friends):
        return client.post(reverse("map"), {"title": "Apéro", "lat": "48.85", "lng": "2.35", "friends": friends})

    def test_suspended_and_unknown_usernames_are_ignored(self, auth_client, other_user, suspended):
        self.create_spot(auth_client, [other_user.username, suspended.username, "nobody"])
        assert list(BeerSpot.objects.get().friends.all()) == [other_user]

    def test_suspended_friend_receives_no_invitation(self, auth_client, suspended):
        self.create_spot(auth_client, [suspended.username])
        assert not suspended.notifications.exists()


class TestBreweryManagers:
    @pytest.fixture
    def managed_brewery(self, user):
        return f.make_brewery(managers=[user])

    def test_not_proposed_in_manager_search(self, auth_client, managed_brewery, suspended):
        f.make_user(username="banana")
        response = auth_client.get(reverse("api_search_users_for_manager", args=[managed_brewery.slug]), {"q": "ban"})
        assert [u["username"] for u in response.json()["users"]] == ["banana"]

    def test_cannot_be_added_as_manager(self, auth_client, managed_brewery, suspended):
        response = auth_client.post(reverse("add_brewery_manager", args=[managed_brewery.slug]), {"username": suspended.username})
        assert response.status_code == 404
        assert not managed_brewery.managers.filter(pk=suspended.pk).exists()


def test_new_accounts_are_active_by_default():
    assert f.make_user().is_active and BeerUser._meta.get_field("is_active").default is True
