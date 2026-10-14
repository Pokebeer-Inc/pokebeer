"""Structure du code : base commune des établissements, rôles de gérant, Nominatim, chargeurs « Charger plus », lieux, navigation, dépendances."""
from pathlib import Path
from unittest import mock

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.urls import reverse

from app.models import Bar, Brewery, QuotaUsage
from app.models.establishments import Establishment
from app.services.establishments import nominatim, spots
from app.services.common.upstream import UpstreamUnavailable
from tests import factories as f

pytestmark = pytest.mark.django_db


class TestEstablishmentBase:
    def test_breweries_and_bars_share_one_definition_of_their_common_fields(self):
        common = {"name", "slug", "siret", "phone", "email", "website", "instagram", "facebook", "latitude", "longitude"}
        for model in (Brewery, Bar):
            assert issubclass(model, Establishment) and common <= {field.name for field in model._meta.get_fields()}

    def test_each_keeps_what_is_specific_to_it(self):
        assert "added_by" in {f.name for f in Bar._meta.get_fields()} and "added_by" not in {f.name for f in Brewery._meta.get_fields()}
        assert Brewery._meta.get_field("managers").remote_field.related_name == "managed_breweries"
        assert Bar._meta.get_field("managers").remote_field.related_name == "managed_bars"

    def test_str_is_the_name_and_ordering_is_by_name(self, geocoder):
        assert str(f.make_bar(name="Chez Moi")) == "Chez Moi" and Bar._meta.ordering == Brewery._meta.ordering == ["name"]


class TestManagerRoles:
    @pytest.mark.parametrize("make, group, related", [(f.make_brewery, "Brasseur", "managed_breweries"), (f.make_bar, "Bartender", "managed_bars")])
    def test_the_role_follows_the_managed_places(self, geocoder, user, make, group, related):
        first, second = make(), make()
        first.managers.add(user)
        assert user.groups.filter(name=group).exists()
        second.managers.add(user)
        first.managers.remove(user)
        assert user.groups.filter(name=group).exists()  # il gère encore l'autre
        second.managers.remove(user)
        assert not user.groups.filter(name=group).exists()

    def test_clearing_all_managers_at_once_removes_the_role_of_those_who_manage_nothing_else(self, geocoder, user, other_user):
        shared, only_other = f.make_brewery(), f.make_brewery()
        shared.managers.add(user, other_user)
        only_other.managers.add(other_user)
        shared.managers.clear()
        assert not user.groups.filter(name="Brasseur").exists() and other_user.groups.filter(name="Brasseur").exists()

    def test_brewer_and_bartender_roles_are_independent(self, geocoder, user):
        f.make_bar().managers.add(user)
        assert user.groups.filter(name="Bartender").exists() and not Group.objects.filter(name="Brasseur", user=user).exists()


class TestNominatim:
    def test_search_returns_the_first_result(self, monkeypatch):
        get = mock.Mock(return_value=[{"lat": "1", "lon": "2"}, {"lat": "3", "lon": "4"}])
        monkeypatch.setattr("app.services.common.upstream.get_json", get)
        assert nominatim.search("Lille", timeout=2) == {"lat": "1", "lon": "2"}
        assert get.call_args.args[0] == settings.NOMINATIM_URL and get.call_args.kwargs["params"]["q"] == "Lille" and get.call_args.kwargs["timeout"] == 2

    @pytest.mark.parametrize("answer", [None, [], "texte", [None]])
    def test_search_without_a_usable_result_gives_none(self, monkeypatch, answer):
        monkeypatch.setattr("app.services.common.upstream.get_json", mock.Mock(return_value=answer))
        assert nominatim.search("Nulle part") is None

    def test_reverse_asks_for_the_french_address_of_a_rounded_point(self, monkeypatch):
        get = mock.Mock(return_value={"address": {}})
        monkeypatch.setattr("app.services.common.upstream.get_json", get)
        nominatim.reverse(50.62912, 3.05726, timeout=2)
        assert get.call_args.args[0] == settings.NOMINATIM_REVERSE_URL
        assert get.call_args.kwargs["params"] == {"lat": "50.6291", "lon": "3.0573", "format": "jsonv2", "zoom": 18, "addressdetails": 1, "accept-language": "fr"}

    @pytest.mark.parametrize("answer", [None, {"error": "Unable to geocode"}])
    def test_reverse_refuses_an_unknown_point(self, monkeypatch, answer):
        monkeypatch.setattr("app.services.common.upstream.get_json", mock.Mock(return_value=answer))
        with pytest.raises(ValueError):
            nominatim.reverse(1, 1)

    def test_an_unavailable_service_is_reported_as_such(self, monkeypatch):
        monkeypatch.setattr("app.services.common.upstream.get_json", mock.Mock(side_effect=UpstreamUnavailable))
        with pytest.raises(UpstreamUnavailable):
            nominatim.search("Lille")

    def test_every_call_goes_through_the_shared_upstream_client(self):
        offenders = []
        for path in Path(settings.BASE_DIR, "app").rglob("*.py"):
            if "migrations" in path.parts or path.name == "upstream.py" or "management" in path.parts:
                continue
            text = path.read_text()
            if "nominatim.openstreetmap.org" in text and path.name not in ("settings.py", "csp.py"):
                offenders.append(path.name)
        assert not offenders


class TestPlaceGeocodingSignal:
    def test_coordinates_follow_the_address_through_the_signal_not_the_model(self, geocoder):
        brewery = f.make_brewery(address="1 rue de la Soif, Paris")
        assert (brewery.latitude, brewery.longitude) == (48.8566, 2.3522) and geocoder.call_count == 1

    def test_the_models_do_not_import_any_service_that_calls_the_network(self):
        text = Path(settings.BASE_DIR, "app", "models", "mixins.py").read_text()
        assert "nominatim" not in text and "requests" not in text


class TestEmbeddingSignal:
    def test_the_beer_model_only_flags_the_stale_vector(self, monkeypatch, django_capture_on_commit_callbacks):
        calls = []
        monkeypatch.setattr("app.services.assistant.ai.get_embedding", lambda text: calls.append(text) or [0.1] * 1024)
        with django_capture_on_commit_callbacks(execute=True):
            beer = f.make_beer()
        assert beer.embedding_is_stale and calls  # le recalcul vient du signal, pas du modèle
        assert "services.ai" not in Path(settings.BASE_DIR, "app", "models", "beers.py").read_text()


class TestNotificationPolicyWiring:
    def test_the_model_package_has_no_dependency_on_the_policy_module(self):
        imports = [line for line in Path(settings.BASE_DIR, "app", "models", "notifications.py").read_text().splitlines() if line.startswith(("import", "from"))]
        assert not any("notification_policy" in line for line in imports)

    def test_the_service_applies_the_policy(self, user, other_user):
        from app.models import Notification
        from app.services.messaging.notifications import save_notifications
        f.block(user, other_user)
        assert save_notifications([Notification(recipient=user, sender=other_user, notif_type="follow")]) == []


class TestLoadMoreRegistry:
    def test_every_list_has_its_loader(self):
        from app.views import load_more
        assert set(load_more.LOADERS) == {
            "search_beers", "search_users", "search_breweries", "search_bars", "wishlist_tiles", "notebook_drinks", "added_beers",
            "notebook_feedback", "followers", "following", "public_added_beers", "public_drinks", "brewery_beers", "beer_reviews", "deleted_beers",
            "pick_drinks",
        }

    def test_a_new_list_only_needs_a_declared_loader(self, auth_client, monkeypatch):
        from app.views import load_more
        monkeypatch.setitem(load_more.LOADERS, "demo", lambda request, offset, limit: load_more.Page([1] * limit, "partials/empty_state.html", {}))
        body = auth_client.get(reverse("load_more_generic", args=["demo"]), {"offset": 0}).json()
        assert body["has_more"] is True

    def test_unknown_lists_and_bad_offsets_are_refused(self, auth_client):
        assert auth_client.get(reverse("load_more_generic", args=["nope"])).status_code == 400
        assert auth_client.get(reverse("load_more_generic", args=["search_beers"]), {"offset": "x"}).status_code == 400

    def test_a_loader_can_refuse_with_its_own_status(self, auth_client, other_user, user):
        f.block(other_user, user)
        assert auth_client.get(reverse("load_more_generic", args=["public_drinks"]), {"username": other_user.username}).status_code == 403
        assert auth_client.get(reverse("load_more_generic", args=["public_drinks"])).status_code == 400


class TestSpotsService:
    def test_the_creator_and_invited_friends_may_edit(self, user, other_user):
        spot = f.make_spot(user, friends=[other_user])
        assert spots.can_edit(spot, user) and spots.can_edit(spot, other_user) and not spots.can_edit(spot, f.make_user())

    def test_friends_added_later_get_an_invitation_the_others_an_update(self, user, other_user):
        from app.models import Notification
        third = f.make_user()
        spot = f.make_spot(user, friends=[other_user])
        spots.update_spot(spot, user, {"title": "Nouveau titre"}, [], [other_user.id, third.id])
        assert Notification.objects.filter(recipient=third, notif_type="spot_invite").exists()
        assert Notification.objects.filter(recipient=other_user, notif_type="spot_updated").exists()
        assert not Notification.objects.filter(recipient=third, notif_type="spot_updated").exists()

    def test_a_friend_cannot_change_the_guest_list(self, user, other_user):
        spot = f.make_spot(user, friends=[other_user])
        spots.update_spot(spot, other_user, {"title": "Par un ami"}, [], [])
        assert list(spot.friends.all()) == [other_user]


class TestQuotaUsage:
    def test_the_model_serves_every_quota_not_only_the_chat(self, user):
        usage = QuotaUsage.objects.create(user=user, day="2026-01-01", scope="label", count=1)
        assert user.quota_usages.get() == usage and "chatusage" not in QuotaUsage._meta.db_table


class TestNavigation:
    @pytest.mark.parametrize("url_name, label", [("index", "Recherche"), ("map", "Carte"), ("notebook", "Carnet"), ("account", "Profil")])
    def test_the_current_page_is_marked_in_the_bar(self, auth_client, url_name, label):
        html = auth_client.get(reverse(url_name)).content.decode()
        bar = html[html.index('aria-label="Navigation principale"'):]
        marked = [part for part in bar.split("<a ") if "aria-current" in part][0]
        assert label in marked

    def test_the_five_entries_are_always_there(self, auth_client):
        html = auth_client.get(reverse("map")).content.decode()
        assert all(reverse(name) in html for name in ("index", "map", "add_beer", "notebook", "account"))


class TestDependencies:
    def test_every_direct_dependency_is_pinned_and_present_in_the_lock(self):
        root = Path(settings.BASE_DIR)
        direct = [line.split("#")[0].strip() for line in (root / "requirements.in").read_text().splitlines() if line.split("#")[0].strip()]
        lock = {line.split("==")[0].lower().replace("_", "-") for line in (root / "requirements.txt").read_text().splitlines() if "==" in line}
        assert all("==" in dependency for dependency in direct)
        assert {dependency.split("==")[0].lower().replace("_", "-") for dependency in direct} <= lock

    def test_the_fake_dotenv_package_and_unused_tools_are_gone(self):
        lock = Path(settings.BASE_DIR, "requirements.txt").read_text().lower()
        for unused in ("\ndotenv==", "cookiecutter", "django-cors-headers", "jinja2", "websockets", "django-browser-reload"):
            assert unused not in lock
