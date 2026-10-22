import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
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

    def test_a_spot_without_description_leaves_the_edit_field_empty(self, auth_client, user):
        """Sans description (NULL), la fenêtre de modification ne doit pas se remplir du texte « None » (qui serait ensuite enregistré)."""
        f.make_spot(user, description=None)
        assert 'data-desc=""' in auth_client.get(URL).content.decode()

    def test_souvenir_list_shows_own_and_shared_spots_most_recent_first(self, auth_client, user, other_user):
        old = f.make_spot(user, title="Ancien", date="2026-01-01")
        recent = f.make_spot(other_user, title="Recent", date="2026-06-01", friends=[user])
        f.make_spot(f.make_user(), title="Invisible")
        html = auth_client.get(URL).content.decode()
        rows = re.findall(r'data-souvenir="([^"]+)"', html)
        assert rows == [recent.slug, old.slug]
        assert f"Partagé par {other_user.username}" in html and "Invisible" not in html.split("pb-sheet")[1]

    def test_souvenir_sheet_holds_the_add_hint_and_counts_the_spots(self, auth_client, user):
        f.make_spot(user)
        html = auth_client.get(URL).content.decode()
        sheet = html[html.index("data-sheet-panel"):html.index('id="geoloc-btn"')]
        assert "Touchez la carte pour ajouter un souvenir" in sheet and ">1</span>" in sheet
        assert html.count("Touchez la carte pour ajouter un souvenir") == 1

    def test_empty_souvenir_sheet_still_explains_how_to_add_one(self, auth_client):
        html = auth_client.get(URL).content.decode()
        assert "Aucun souvenir pour l'instant." in html and "data-sheet-list" not in html

    def test_souvenir_titles_are_escaped_in_the_list(self, auth_client, user):
        f.make_spot(user, title="<img src=x onerror=alert(1)>")
        assert "<img src=x onerror" not in auth_client.get(URL).content.decode()

    def test_the_popup_has_a_visible_edit_button(self, auth_client, user):
        spot = f.make_spot(user)
        html = auth_client.get(URL).content.decode()
        assert f"data-on-click=\"openEditModal\" data-no-event data-args='[\"{spot.slug}\"]'" in html

    def test_only_geolocated_places_are_listed(self, auth_client, geocoder):
        geocoded = f.make_bar(address="Lyon")
        f.make_bar(address=None)
        bars = auth_client.get(URL).context["bars"]
        assert [bar["slug"] for bar in bars] == [geocoded.slug]
        assert set(bars[0]) == {"slug", "name", "latitude", "longitude"}  # quatre colonnes, pas la fiche entière


class TestCreateSpot:
    def test_creates_spot_with_drinks_and_invites_friends(self, auth_client, user, other_user):
        drink = f.make_drink(user)
        assert_redirects(auth_client.post(URL, spot_data(drinks=[drink.slug], friends=[other_user.username])), URL)

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
        ({"title": "x" * 151}, "Titre"), ({"spot_slug": "pas un slug!"}, "Lieu"), ({"spot_slug": "x" * 151}, "Lieu"),
    ])
    def test_invalid_values_are_refused_with_an_explanation(self, auth_client, overrides, label):
        response = auth_client.post(URL, spot_data(**overrides))
        assert_redirects(response, URL)
        assert not BeerSpot.objects.exists()
        assert any(message.startswith("Le point n'a pas pu être enregistré") and f"{label} :" in message for message in messages_of(response))

    def test_missing_date_defaults_to_today(self, auth_client):
        auth_client.post(URL, spot_data(date=""))
        assert BeerSpot.objects.get().date == timezone.localdate()

    def test_unknown_drink_slugs_are_ignored(self, auth_client, user):
        drink = f.make_drink(user)
        assert_redirects(auth_client.post(URL, spot_data(drinks=[drink.slug, "abc", "1.5"])), URL)
        assert list(BeerSpot.objects.get().drinks.all()) == [drink]

    def test_tastings_of_people_outside_the_spot_are_ignored(self, auth_client, user, other_user):
        own = f.make_drink(user)
        auth_client.post(URL, spot_data(drinks=[own.slug, f.make_drink(other_user).slug]))
        assert list(BeerSpot.objects.get().drinks.all()) == [own]

    def test_creator_can_attach_an_invited_friend_tasting(self, auth_client, other_user):
        friend_drink = f.make_drink(other_user)
        auth_client.post(URL, spot_data(drinks=[friend_drink.slug], friends=[other_user.username]))
        assert list(BeerSpot.objects.get().drinks.all()) == [friend_drink]


class TestEditSpot:
    def test_owner_edits_and_new_friends_get_an_invitation(self, auth_client, user, other_user):
        old_friend = f.make_user()
        spot = f.make_spot(user, friends=[old_friend])

        auth_client.post(URL, spot_data(spot_slug=spot.slug, title="Renommé", friends=[old_friend.username, other_user.username]))

        spot.refresh_from_db()
        assert spot.title == "Renommé"
        assert set(Notification.objects.values_list("recipient", "notif_type")) == {
            (other_user.id, "spot_invite"), (old_friend.id, "spot_updated"),
        }

    def test_friend_can_edit_but_not_change_invitees(self, other_client, user, other_user):
        spot = f.make_spot(user, friends=[other_user])
        other_client.post(URL, spot_data(spot_slug=spot.slug, title="Par un ami", friends=[]))
        spot.refresh_from_db()
        assert spot.title == "Par un ami"
        assert list(spot.friends.all()) == [other_user]
        assert Notification.objects.get().recipient == user

    def test_friend_adds_his_tastings_next_to_the_creator_ones(self, other_client, user, other_user):
        creator_drink, friend_drink = f.make_drink(user), f.make_drink(other_user)
        spot = f.make_spot(user, friends=[other_user], drinks=[creator_drink])
        other_client.post(URL, spot_data(spot_slug=spot.slug, drinks=[friend_drink.slug]))
        assert set(spot.drinks.all()) == {creator_drink, friend_drink}

    def test_friend_cannot_attach_a_stranger_tasting(self, other_client, user, other_user):
        spot = f.make_spot(user, friends=[other_user])
        other_client.post(URL, spot_data(spot_slug=spot.slug, drinks=[f.make_drink(f.make_user()).slug]))
        assert not spot.drinks.exists()

    def test_beer_already_shared_by_someone_else_is_not_duplicated(self, other_client, user, other_user, beer):
        creator_drink = f.make_drink(user, beer)
        spot = f.make_spot(user, friends=[other_user], drinks=[creator_drink])
        other_client.post(URL, spot_data(spot_slug=spot.slug, drinks=[f.make_drink(other_user, beer).slug]))
        assert list(spot.drinks.all()) == [creator_drink]

    def test_stranger_cannot_edit(self, other_client, user):
        spot = f.make_spot(user, title="Intact")
        other_client.post(URL, spot_data(spot_slug=spot.slug, title="Piraté"))
        spot.refresh_from_db()
        assert spot.title == "Intact"

    def test_unknown_spot_is_404(self, auth_client):
        assert auth_client.post(URL, spot_data(spot_slug="unknown-slug")).status_code == 404

    @pytest.mark.parametrize("overrides", [{"lat": "abc"}, {"lng": "200"}, {"date": "demain"}])
    def test_invalid_edit_leaves_the_spot_untouched(self, auth_client, user, overrides):
        spot = f.make_spot(user, title="Intact")
        assert_redirects(auth_client.post(URL, spot_data(spot_slug=spot.slug, title="Modifié", **overrides)), URL)
        spot.refresh_from_db()
        assert (spot.title, spot.latitude, spot.longitude) == ("Intact", 48.85, 2.35)


class TestDeleteSpot:
    def test_owner_deletes_with_post_only(self, auth_client, user):
        spot = f.make_spot(user)
        auth_client.get(reverse("delete_spot", args=[spot.slug]))
        assert BeerSpot.objects.exists()
        auth_client.post(reverse("delete_spot", args=[spot.slug]))
        assert not BeerSpot.objects.exists()

    def test_friend_cannot_delete(self, other_client, user, other_user):
        spot = f.make_spot(user, friends=[other_user])
        assert other_client.post(reverse("delete_spot", args=[spot.slug])).status_code == 404
        assert BeerSpot.objects.exists()


class TestSpotPhoto:
    def test_photo_is_optional(self, auth_client):
        auth_client.post(URL, spot_data())
        spot = BeerSpot.objects.get()
        assert not spot.photo and spot.photo_url is None

    def test_photo_is_stored_as_webp_in_the_spots_folder(self, auth_client):
        auth_client.post(URL, spot_data(photo=f.make_image_upload()))
        spot = BeerSpot.objects.get()
        assert spot.photo.name.startswith("spots/") and spot.photo.name.endswith(".webp")
        assert spot.photo_url == spot.photo.url

    def test_invalid_file_refuses_the_spot(self, auth_client):
        response = auth_client.post(URL, spot_data(photo=SimpleUploadedFile("a.png", b"not an image")))
        assert not BeerSpot.objects.exists()
        assert any("Photo :" in message for message in messages_of(response))

    def test_daily_quota_is_enforced(self, auth_client, monkeypatch):
        monkeypatch.setattr("app.forms.SPOT_PHOTO_DAILY_LIMIT", 0)
        auth_client.post(URL, spot_data(photo=f.make_image_upload()))
        assert not BeerSpot.objects.exists()

    def test_photo_can_be_replaced_and_removed(self, auth_client, user, django_capture_on_commit_callbacks):
        spot = f.make_spot(user)
        auth_client.post(URL, spot_data(spot_slug=spot.slug, photo=f.make_image_upload()))
        spot.refresh_from_db()
        first = spot.photo.name
        assert first

        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(URL, spot_data(spot_slug=spot.slug, photo=f.make_image_upload()))
        spot.refresh_from_db()
        assert spot.photo.name != first and not spot.photo.storage.exists(first)

        second = spot.photo.name
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(URL, spot_data(spot_slug=spot.slug, remove_photo="on"))
        spot.refresh_from_db()
        assert not spot.photo and not spot.photo_url and not spot.photo.storage.exists(second)

    def test_editing_without_a_photo_keeps_the_existing_one(self, auth_client, user):
        spot = f.make_spot(user)
        auth_client.post(URL, spot_data(spot_slug=spot.slug, photo=f.make_image_upload()))
        spot.refresh_from_db()
        kept = spot.photo.name
        auth_client.post(URL, spot_data(spot_slug=spot.slug, title="Renommé"))
        spot.refresh_from_db()
        assert spot.photo.name == kept

    def test_deleting_the_spot_deletes_its_photo(self, auth_client, user, django_capture_on_commit_callbacks):
        spot = f.make_spot(user)
        auth_client.post(URL, spot_data(spot_slug=spot.slug, photo=f.make_image_upload()))
        spot.refresh_from_db()
        storage, name = spot.photo.storage, spot.photo.name
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(reverse("delete_spot", args=[spot.slug]))
        assert not storage.exists(name)

    def test_stranger_cannot_change_the_photo(self, other_client, user):
        spot = f.make_spot(user)
        other_client.post(URL, spot_data(spot_slug=spot.slug, photo=f.make_image_upload()))
        spot.refresh_from_db()
        assert not spot.photo

    def test_popup_shows_the_photo(self, auth_client, user):
        spot = f.make_spot(user)
        auth_client.post(URL, spot_data(spot_slug=spot.slug, photo=f.make_image_upload()))
        spot.refresh_from_db()
        assert spot.photo_url in auth_client.get(URL).content.decode()


class TestPlacePopup:
    def popup(self, client, kind, place):
        return client.get(reverse("map_place_popup", args=[kind, place.slug]))

    def test_shows_image_name_description_and_address_in_that_order(self, auth_client, geocoder):
        bar = f.make_bar(name="Le Troubadour", description="Un bar chaleureux", postal_code="69001", city="Lyon", image=f.make_image_upload())
        html = self.popup(auth_client, "bar", bar).content.decode()
        positions = [html.index(text) for text in (bar.image.url, "Le Troubadour", "Un bar chaleureux", "69001 Lyon")]
        assert positions == sorted(positions)
        assert reverse("bar_detail", args=[bar.slug]) in html

    def test_offers_directions_next_to_the_link_to_the_page(self, auth_client, geocoder):
        bar = f.make_bar(name="Le Troubadour", postal_code="69001", city="Lyon", street="1 rue de la Paix")
        html = self.popup(auth_client, "bar", bar).content.decode()
        assert "Voir la fiche" in html and "Y aller" in html and html.index("Voir la fiche") < html.index("Y aller")
        assert "https://www.google.com/maps/dir/?" in html and "data-apple-url=\"https://maps.apple.com/?" in html

    def test_no_directions_button_for_a_place_without_address_or_position(self, auth_client):
        html = self.popup(auth_client, "bar", f.make_bar()).content.decode()
        assert "Voir la fiche" in html and "Y aller" not in html

    def test_no_image_means_no_image_tag(self, auth_client, geocoder):
        brewery = f.make_brewery(name="Sans image")
        html = self.popup(auth_client, "brewery", brewery).content.decode()
        assert "Sans image" in html and "<img" not in html

    def test_text_is_escaped(self, auth_client, geocoder):
        bar = f.make_bar(name="Bar", description="<script>alert(1)</script>")
        assert "<script>alert(1)" not in self.popup(auth_client, "bar", bar).content.decode()

    def test_unknown_kind_or_slug_is_404(self, auth_client, geocoder):
        bar = f.make_bar()
        assert self.popup(auth_client, "cave", bar).status_code == 404
        assert auth_client.get(reverse("map_place_popup", args=["bar", "inconnu"])).status_code == 404

    def test_requires_login(self, client, geocoder):
        bar = f.make_bar()
        assert self.popup(client, "bar", bar).status_code == 302
