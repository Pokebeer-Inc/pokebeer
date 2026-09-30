import pytest
from django.urls import reverse
from django.utils import timezone

from app.models import BeerSpot, Notification
from tests import factories as f
from tests.helpers import assert_redirects, messages_of

pytestmark = pytest.mark.django_db

URL = reverse("map")


def spot_data(**overrides):
    return {"title": "Terrasse", "description": "Soleil", "date": "2026-06-21", "lat": "45.76", "lng": "4.83", **overrides}


class TestMapPage:
    def test_shows_own_and_shared_spots_but_not_blocked_ones(self, auth_client, user, other_user):
        own = f.make_spot(user)
        shared = f.make_spot(other_user, friends=[user])
        f.make_spot(f.make_user())
        blocked_owner = f.make_user()
        f.make_spot(blocked_owner, friends=[user])
        f.block(user, blocked_owner)

        spots = auth_client.get(URL).context["user_spots"]

        assert set(spots) == {own, shared}

    def test_only_geolocated_places_are_listed(self, auth_client, geocoder):
        geocoded = f.make_bar(address="Lyon")
        f.make_bar(address=None)
        assert list(auth_client.get(URL).context["bars"]) == [geocoded]


class TestCreateSpot:
    def test_creates_spot_with_drinks_and_invites_friends(self, auth_client, user, other_user):
        drink = f.make_drink(user)
        assert_redirects(auth_client.post(URL, spot_data(drinks=[drink.id], friends=[other_user.id])), URL)

        spot = BeerSpot.objects.get()
        assert (spot.user, spot.latitude, spot.longitude) == (user, 45.76, 4.83)
        assert list(spot.drinks.all()) == [drink] and list(spot.friends.all()) == [other_user]
        assert Notification.objects.get().notif_type == "spot_invite"

    @pytest.mark.parametrize("missing", ["title", "lat", "lng"])
    def test_required_fields(self, auth_client, missing):
        auth_client.post(URL, spot_data(**{missing: ""}))
        assert not BeerSpot.objects.exists()

    @pytest.mark.parametrize("lat, lng", [("90", "180"), ("-90", "-180"), ("0", "0")])
    def test_coordinate_limits_are_accepted(self, auth_client, lat, lng):
        auth_client.post(URL, spot_data(lat=lat, lng=lng))
        assert BeerSpot.objects.exists()

    @pytest.mark.parametrize("overrides, label", [
        ({"lat": "abc"}, "Latitude"), ({"lng": "abc"}, "Longitude"),
        ({"lat": "nan"}, "Latitude"), ({"lng": "inf"}, "Longitude"), ({"lat": "-inf"}, "Latitude"),
        ({"lat": "90.0001"}, "Latitude"), ({"lat": "-91"}, "Latitude"),
        ({"lng": "180.5"}, "Longitude"), ({"lng": "-181"}, "Longitude"),
        ({"date": "pas-une-date"}, "Date"), ({"date": "2026-02-30"}, "Date"),
        ({"title": "x" * 151}, "Titre"), ({"spot_id": "abc"}, "Lieu"), ({"spot_id": "-3"}, "Lieu"),
    ])
    def test_invalid_values_are_refused_with_an_explanation(self, auth_client, overrides, label):
        response = auth_client.post(URL, spot_data(**overrides))
        assert_redirects(response, URL)
        assert not BeerSpot.objects.exists()
        assert any(message.startswith("Le point n'a pas pu être enregistré") and f"{label} :" in message for message in messages_of(response))

    def test_missing_date_defaults_to_today(self, auth_client):
        auth_client.post(URL, spot_data(date=""))
        assert BeerSpot.objects.get().date == timezone.localdate()

    def test_non_numeric_drink_ids_are_ignored(self, auth_client, user):
        drink = f.make_drink(user)
        assert_redirects(auth_client.post(URL, spot_data(drinks=[drink.id, "abc", "1.5"])), URL)
        assert list(BeerSpot.objects.get().drinks.all()) == [drink]

    def test_tastings_of_people_outside_the_spot_are_ignored(self, auth_client, user, other_user):
        own = f.make_drink(user)
        auth_client.post(URL, spot_data(drinks=[own.id, f.make_drink(other_user).id]))
        assert list(BeerSpot.objects.get().drinks.all()) == [own]

    def test_creator_can_attach_an_invited_friend_tasting(self, auth_client, other_user):
        friend_drink = f.make_drink(other_user)
        auth_client.post(URL, spot_data(drinks=[friend_drink.id], friends=[other_user.id]))
        assert list(BeerSpot.objects.get().drinks.all()) == [friend_drink]


class TestEditSpot:
    def test_owner_edits_and_new_friends_get_an_invitation(self, auth_client, user, other_user):
        old_friend = f.make_user()
        spot = f.make_spot(user, friends=[old_friend])

        auth_client.post(URL, spot_data(spot_id=spot.id, title="Renommé", friends=[old_friend.id, other_user.id]))

        spot.refresh_from_db()
        assert spot.title == "Renommé"
        assert set(Notification.objects.values_list("recipient", "notif_type")) == {
            (other_user.id, "spot_invite"), (old_friend.id, "spot_updated"),
        }

    def test_friend_can_edit_but_not_change_invitees(self, other_client, user, other_user):
        spot = f.make_spot(user, friends=[other_user])
        other_client.post(URL, spot_data(spot_id=spot.id, title="Par un ami", friends=[]))
        spot.refresh_from_db()
        assert spot.title == "Par un ami"
        assert list(spot.friends.all()) == [other_user]
        assert Notification.objects.get().recipient == user

    def test_friend_adds_his_tastings_next_to_the_creator_ones(self, other_client, user, other_user):
        creator_drink, friend_drink = f.make_drink(user), f.make_drink(other_user)
        spot = f.make_spot(user, friends=[other_user], drinks=[creator_drink])
        other_client.post(URL, spot_data(spot_id=spot.id, drinks=[friend_drink.id]))
        assert set(spot.drinks.all()) == {creator_drink, friend_drink}

    def test_friend_cannot_attach_a_stranger_tasting(self, other_client, user, other_user):
        spot = f.make_spot(user, friends=[other_user])
        other_client.post(URL, spot_data(spot_id=spot.id, drinks=[f.make_drink(f.make_user()).id]))
        assert not spot.drinks.exists()

    def test_beer_already_shared_by_someone_else_is_not_duplicated(self, other_client, user, other_user, beer):
        creator_drink = f.make_drink(user, beer)
        spot = f.make_spot(user, friends=[other_user], drinks=[creator_drink])
        other_client.post(URL, spot_data(spot_id=spot.id, drinks=[f.make_drink(other_user, beer).id]))
        assert list(spot.drinks.all()) == [creator_drink]

    def test_stranger_cannot_edit(self, other_client, user):
        spot = f.make_spot(user, title="Intact")
        other_client.post(URL, spot_data(spot_id=spot.id, title="Piraté"))
        spot.refresh_from_db()
        assert spot.title == "Intact"

    def test_unknown_spot_is_404(self, auth_client):
        assert auth_client.post(URL, spot_data(spot_id=999999)).status_code == 404

    @pytest.mark.parametrize("overrides", [{"lat": "abc"}, {"lng": "200"}, {"date": "demain"}])
    def test_invalid_edit_leaves_the_spot_untouched(self, auth_client, user, overrides):
        spot = f.make_spot(user, title="Intact")
        assert_redirects(auth_client.post(URL, spot_data(spot_id=spot.id, title="Modifié", **overrides)), URL)
        spot.refresh_from_db()
        assert (spot.title, spot.latitude, spot.longitude) == ("Intact", 48.85, 2.35)


class TestDeleteSpot:
    def test_owner_deletes_with_post_only(self, auth_client, user):
        spot = f.make_spot(user)
        auth_client.get(reverse("delete_spot", args=[spot.id]))
        assert BeerSpot.objects.exists()
        auth_client.post(reverse("delete_spot", args=[spot.id]))
        assert not BeerSpot.objects.exists()

    def test_friend_cannot_delete(self, other_client, user, other_user):
        spot = f.make_spot(user, friends=[other_user])
        assert other_client.post(reverse("delete_spot", args=[spot.id])).status_code == 404
        assert BeerSpot.objects.exists()
