import csv
import io
import zipfile
from datetime import date
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse

from app.models import ReverseGeocode
from app.services import reverse_geocoding as rg
from app.services.analytics import export
from app.services.analytics.blocks import Chart, Table
from app.services.analytics.periods import Period
from app.services.analytics.privacy import MIN_GROUP_SIZE, group_publishable
from app.services.analytics.spots import spot_points
from tests import factories as f

pytestmark = pytest.mark.django_db
Kind = ReverseGeocode.PlaceKind


def payload(category, type_, **address):
    return {"category": category, "type": type_, "address": address}


class TestClassify:
    @pytest.mark.parametrize("category, type_, expected", [
        ("building", "house", Kind.HOME), ("building", "apartments", Kind.HOME), ("place", "house", Kind.HOME),
        ("amenity", "pub", Kind.BAR), ("amenity", "restaurant", Kind.BAR), ("craft", "brewery", Kind.BREWERY),
        ("industrial", "brewery", Kind.BREWERY), ("leisure", "park", Kind.OUTDOOR), ("natural", "wood", Kind.OUTDOOR),
        ("highway", "residential", Kind.STREET), ("shop", "supermarket", Kind.OTHER), ("", "", Kind.OTHER),
    ])
    def test_place_kind(self, category, type_, expected):
        assert rg.classify(payload(category, type_))["place_kind"] == expected

    @pytest.mark.parametrize("address, settlement, urban, city", [
        ({"city": "Lyon"}, "city", True, "Lyon"), ({"town": "Annecy"}, "town", True, "Annecy"),
        ({"village": "Vaulx"}, "village", False, "Vaulx"), ({"hamlet": "Le Haut"}, "hamlet", False, "Le Haut"),
        ({}, "", None, ""),
    ])
    def test_settlement_and_urbanity(self, address, settlement, urban, city):
        fields = rg.classify(payload("building", "house", **address))
        assert (fields["settlement"], fields["is_urban"], fields["city"]) == (settlement, urban, city)

    def test_administrative_levels_are_kept(self):
        fields = rg.classify(payload("amenity", "bar", city="Lyon", county="Rhône", state="Auvergne-Rhône-Alpes", country_code="FR", postcode="69001"))
        assert (fields["department"], fields["region"], fields["country_code"], fields["postcode"]) == ("Rhône", "Auvergne-Rhône-Alpes", "fr", "69001")


class TestResolvePending:
    def test_positions_are_cached_and_deduplicated(self, user, other_user):
        f.make_spot(user, latitude=48.85001, longitude=2.35001)
        f.make_spot(other_user, latitude=48.85002, longitude=2.35002)  # même position à ~11 m près
        fetch = mock.Mock(return_value=payload("amenity", "bar", city="Paris"))
        assert rg.resolve_pending(fetch=fetch, sleep=lambda s: None) == {"resolved": 1, "failed": 0}
        assert fetch.call_count == 1 and ReverseGeocode.objects.get().place_kind == Kind.BAR
        assert rg.pending_keys() == []

    def test_only_rounded_coordinates_are_sent(self, user):
        f.make_spot(user, latitude=48.8566149, longitude=2.3522219)
        fetch = mock.Mock(return_value=payload("building", "house"))
        rg.resolve_pending(fetch=fetch, sleep=lambda s: None)
        assert fetch.call_args.args == (48.8566, 2.3522)

    def test_failures_are_retried_then_abandoned(self, user):
        f.make_spot(user)
        fetch = mock.Mock(side_effect=ConnectionError("down"))
        for _ in range(rg.MAX_ATTEMPTS + 2):
            rg.resolve_pending(fetch=fetch, sleep=lambda s: None)
        assert fetch.call_count == rg.MAX_ATTEMPTS and not ReverseGeocode.objects.get().is_resolved

    def test_one_failure_does_not_stop_the_batch(self, user):
        f.make_spot(user, latitude=48.0, longitude=2.0)
        f.make_spot(user, latitude=49.0, longitude=3.0)
        fetch = mock.Mock(side_effect=[ValueError("inconnu"), payload("amenity", "pub")])
        assert rg.resolve_pending(fetch=fetch, sleep=lambda s: None) == {"resolved": 1, "failed": 1}

    def test_limit_and_rate_limiting(self, user):
        for i in range(3):
            f.make_spot(user, latitude=40.0 + i, longitude=2.0)
        sleep = mock.Mock()
        rg.resolve_pending(limit=2, fetch=mock.Mock(return_value=payload("amenity", "bar")), sleep=sleep)
        assert ReverseGeocode.objects.count() == 2 and sleep.call_args.args == (rg.REQUEST_DELAY,) and sleep.call_count == 1

    def test_command_runs_the_job(self, user, monkeypatch):
        f.make_spot(user)
        monkeypatch.setattr(rg, "fetch_payload", mock.Mock(return_value=payload("amenity", "bar")))
        out = io.StringIO()
        call_command("geocode_spots", "--limit", "5", stdout=out)
        assert "1 résolue" in out.getvalue()

    def test_no_network_call_while_rendering_pages(self, client_for, staff, user, monkeypatch):
        f.make_spot(user)
        monkeypatch.setattr(rg, "fetch_payload", mock.Mock(side_effect=AssertionError("réseau interdit")))
        assert client_for(staff).get(reverse("admin_analytics", args=["geography"])).status_code == 200


def geocode(spot, **fields):
    lat_e4, lon_e4 = rg.key_for(spot.latitude, spot.longitude)
    from django.utils import timezone
    return ReverseGeocode.objects.update_or_create(lat_e4=lat_e4, lon_e4=lon_e4, defaults={"resolved_at": timezone.now(), **fields})[0]


class TestGeocodedGeography:
    def members(self, count):
        return [f.make_user(username=f.unique("g_")) for _ in range(count)]

    def test_spot_points_carry_the_cached_info(self, user):
        spot = f.make_spot(user)
        geocode(spot, place_kind=Kind.HOME, is_urban=True, city="Paris", department="Paris", region="Île-de-France")
        point = spot_points(Period())[0]
        assert point.resolved and point.zone == "Paris (Paris)" and point.region == "Île-de-France"

    def test_unresolved_spot_falls_back_to_a_grid_zone(self, user):
        f.make_spot(user)
        point = spot_points(Period())[0]
        assert not point.resolved and point.zone.startswith("Zone ")

    def test_real_blocks_appear_once_spots_are_geocoded(self, client_for, staff):
        for member in self.members(MIN_GROUP_SIZE):
            geocode(f.make_spot(member), place_kind=Kind.HOME, is_urban=True, city="Paris")
        blocks = {getattr(b, "id", ""): b for b in client_for(staff).get(reverse("admin_analytics", args=["geography"])).context["blocks"]}
        assert blocks["real-kind"].categories == [Kind.HOME.label] and blocks["real-urban"].categories == ["Ville"]
        assert blocks["cities"].rows[0][0] == "Paris"

    def test_small_categories_and_cities_are_hidden(self, client_for, staff):
        for member in self.members(MIN_GROUP_SIZE - 1):
            geocode(f.make_spot(member, latitude=45.0, longitude=5.0), place_kind=Kind.BAR, city="Petite Ville")
        blocks = {getattr(b, "id", ""): b for b in client_for(staff).get(reverse("admin_analytics", args=["geography"])).context["blocks"]}
        assert "real-kind" not in blocks and blocks["cities"].rows == []

    def test_group_publishable(self):
        P = type("P", (), {})
        points = [type("P", (), {"user_id": i % 4, "k": "a" if i < 8 else "b"})() for i in range(10)]
        rows, hidden = group_publishable(points, lambda p: p.k)
        assert rows == [("a", 8, 4)] and hidden == 2


class TestBarsPage:
    @pytest.fixture
    def bar_scene(self, geocoder):
        bar = f.make_bar(name="Le Zinc", address="Lyon")  # géocodeur factice : 48.8566, 2.3522
        brewery = f.make_brewery(name="Brasserie Z")
        ipa, stout = f.make_beer(name="IPA Z", brewery=brewery, style="IPA"), f.make_beer(name="Stout Z", brewery=brewery, style="Stout")
        for i in range(MIN_GROUP_SIZE):
            member = f.make_user(username=f.unique("b_"))
            drink = f.make_drink(member, ipa, note=8)
            f.make_spot(member, latitude=48.8566, longitude=2.3522, drinks=[drink])
        far = f.make_user(username=f.unique("far_"))
        f.make_spot(far, latitude=43.0, longitude=1.0)
        return bar, stout

    def test_overview_counts_spots_near_each_bar(self, client_for, staff, bar_scene):
        table = next(b for b in client_for(staff).get(reverse("admin_analytics", args=["bars"])).context["blocks"] if getattr(b, "id", "") == "bars-overview")
        assert table.rows == [["Le Zinc", MIN_GROUP_SIZE, MIN_GROUP_SIZE]]

    def test_selected_bar_shows_what_is_drunk_around_it(self, client_for, staff, bar_scene):
        bar, _ = bar_scene
        blocks = {getattr(b, "id", ""): b for b in client_for(staff).get(reverse("admin_analytics", args=["bars"]), {"bar": bar.slug}).context["blocks"]}
        assert blocks["bar-styles"].rows[0][0] == "IPA" and blocks["bar-beers"].rows[0][0] == "IPA Z"
        assert {"bar-weekday", "bar-month"} <= set(blocks)

    def test_quiet_bar_details_are_withheld(self, client_for, staff, geocoder):
        bar = f.make_bar(name="Calme", address="Paris")
        for _ in range(MIN_GROUP_SIZE - 1):
            f.make_spot(f.make_user(username=f.unique("q_")), latitude=48.8566, longitude=2.3522)
        response = client_for(staff).get(reverse("admin_analytics", args=["bars"]), {"bar": bar.slug})
        ids = {getattr(b, "id", "") for b in response.context["blocks"]}
        assert "bar-styles" not in ids and any("Pas assez d'activité" in getattr(b, "text", "") for b in response.context["blocks"])
        overview = next(b for b in response.context["blocks"] if getattr(b, "id", "") == "bars-overview")
        assert overview.rows == [["Calme", "< 3", "< 3"]]

    def test_unknown_bar_slug_is_ignored(self, client_for, staff, bar_scene):
        assert client_for(staff).get(reverse("admin_analytics", args=["bars"]), {"bar": "nope"}).status_code == 200


class TestRegionalDemand:
    def test_where_beers_are_drunk_and_where_styles_lack_the_brewery(self, client_for, staff, geocoder):
        mine, other = f.make_brewery(name="Ma Brasserie"), f.make_brewery(name="Concurrente")
        my_ipa, their_ipa = f.make_beer(name="Mon IPA", brewery=mine, style="IPA"), f.make_beer(name="Leur IPA", brewery=other, style="IPA")
        for city, beer in (("Lyon", my_ipa), ("Nantes", their_ipa)):
            for _ in range(MIN_GROUP_SIZE):
                member = f.make_user(username=f.unique("r_"))
                drink = f.make_drink(member, beer)
                spot = f.make_spot(member, latitude=45.76 if city == "Lyon" else 47.21, longitude=4.83 if city == "Lyon" else -1.55, drinks=[drink])
                geocode(spot, place_kind=Kind.BAR, city=city, department="X")
        blocks = {getattr(b, "id", ""): b for b in client_for(staff).get(reverse("admin_analytics", args=["places"]), {"brewery": mine.slug}).context["blocks"]}
        assert blocks["own-zones"].rows == [["Lyon (X)", MIN_GROUP_SIZE, MIN_GROUP_SIZE]]
        assert blocks["potential-zones"].rows == [["Nantes (X)", MIN_GROUP_SIZE, MIN_GROUP_SIZE]]


class TestExport:
    URL = lambda self, page="tastes": reverse("admin_analytics", args=[page])

    @pytest.fixture
    def data(self, geocoder):
        brewery = f.make_brewery(name="B")
        beer = f.make_beer(name="Beer", brewery=brewery, style="IPA")
        for _ in range(4):
            f.make_drink(f.make_user(username=f.unique("e_")), beer, note=8)

    def read(self, response):
        return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))

    def test_block_csv_follows_the_current_filters(self, client_for, staff, data):
        response = client_for(staff).get(self.URL(), {"months": "6", "export": "styles-volume"})
        assert response["Content-Type"].startswith("text/csv") and "6m" in response["Content-Disposition"]
        assert self.read(response) == [["Catégorie", "Dégustations"], ["IPA", "4"]]

    def test_period_filter_changes_the_exported_data(self, client_for, staff, data):
        from datetime import timedelta
        old = f.make_drink(f.make_user(username=f.unique("e_")), f.make_beer(name="Old", style="Stout"), date=date.today() - timedelta(days=200))
        wide = self.read(client_for(staff).get(self.URL(), {"months": "12", "export": "styles-volume"}))
        narrow = self.read(client_for(staff).get(self.URL(), {"months": "3", "export": "styles-volume"}))
        assert ["Stout", "1"] in wide and ["Stout", "1"] not in narrow

    def test_zip_contains_every_exportable_block(self, client_for, staff, data):
        response = client_for(staff).get(self.URL("trends"), {"export": "all"})
        names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
        assert response["Content-Type"] == "application/zip" and "trend-drinks.csv" in names and all(n.endswith(".csv") for n in names)

    def test_table_and_map_blocks_are_exportable(self, client_for, staff, data):
        assert self.read(client_for(staff).get(self.URL(), {"export": "top-beers"}))[0][0] == "Bière"
        assert self.read(client_for(staff).get(self.URL("geography"), {"export": "geo-map"}))[0] == ["Latitude", "Longitude", "Rayon", "Détail"]

    def test_unknown_or_non_exportable_block_is_404(self, client_for, staff, data):
        assert client_for(staff).get(self.URL(), {"export": "nope"}).status_code == 404

    def test_export_requires_staff(self, client, auth_client, data):
        assert "/admin/login/" in client.get(self.URL(), {"export": "all"}).url
        assert auth_client.get(self.URL(), {"export": "all"}).status_code == 302

    def test_download_headers(self, client_for, staff, data):
        response = client_for(staff).get(self.URL(), {"export": "styles-volume"})
        assert response["X-Content-Type-Options"] == "nosniff" and response["Content-Disposition"].startswith("attachment;")

    def test_page_links_carry_the_filters(self, client_for, staff, data):
        html = client_for(staff).get(self.URL(), {"months": "6"}).content.decode()
        assert "months=6&export=styles-volume" in html and "months=6&export=all" in html

    @pytest.mark.parametrize("value, expected", [
        ("=HYPERLINK(\"http://evil\")", "'=HYPERLINK(\"http://evil\")"), ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
        ("-2+3+cmd|x", "'-2+3+cmd|x"), ("@SUM(A1)", "'@SUM(A1)"), ("\t=1", "'\t=1"),
        ("+12 %", "+12 %"), ("-3,5", "-3,5"), ("Brasserie", "Brasserie"), (12, 12), (-3.5, -3.5), (None, ""),
    ])
    def test_formula_injection_is_neutralised(self, value, expected):
        assert export.sanitize(value) == expected

    def test_malicious_labels_are_neutralised_in_the_file(self):
        block = Table("t", "T", ["Style"], [["=1+1"], ["IPA"]])
        assert export.to_csv(block).splitlines()[1:] == ["'=1+1", "IPA"]

    def test_chart_gaps_become_empty_cells(self):
        block = Chart("c", "C", "line", ["a", "b"], [{"name": "S", "data": [1, None]}])
        assert export.to_csv(block).splitlines() == [export.BOM + "Catégorie,S", "a,1", "b,"]


class TestAutomaticGeocoding:
    """Le service n'est appelé que lorsqu'une position nouvelle apparaît."""

    @pytest.fixture
    def fetch(self, monkeypatch):
        mocked = mock.Mock(return_value=payload("amenity", "bar", city="Paris"))
        monkeypatch.setattr(rg, "fetch_payload", mocked)
        return mocked

    @pytest.fixture
    def run(self, django_capture_on_commit_callbacks):
        def _run(action):
            with django_capture_on_commit_callbacks(execute=True):
                return action()
        return _run

    def test_new_spot_is_geocoded_at_creation(self, user, fetch, run):
        run(lambda: f.make_spot(user, latitude=48.85, longitude=2.35))
        assert fetch.call_count == 1 and ReverseGeocode.objects.get().is_resolved

    def test_cached_position_costs_no_call(self, user, other_user, fetch, run):
        run(lambda: f.make_spot(user, latitude=48.85, longitude=2.35))
        run(lambda: f.make_spot(other_user, latitude=48.85001, longitude=2.35001))  # même position à ~11 m
        assert fetch.call_count == 1

    def test_edit_without_moving_costs_nothing(self, user, fetch, run):
        spot = run(lambda: f.make_spot(user, latitude=48.85, longitude=2.35))
        fetch.reset_mock()

        def edit():
            spot.title = "Nouveau titre"
            spot.latitude, spot.longitude = 48.85, 2.35  # le formulaire réaffecte toujours les coordonnées
            spot.save()
        run(edit)
        assert fetch.call_count == 0

    def test_moving_the_spot_geocodes_the_new_position_and_forgets_the_old_one(self, user, fetch, run):
        spot = run(lambda: f.make_spot(user, latitude=48.85, longitude=2.35))

        def move():
            spot.latitude, spot.longitude = 45.76, 4.83
            spot.save()
        run(move)
        assert fetch.call_count == 2
        assert list(ReverseGeocode.objects.values_list("lat_e4", "lon_e4")) == [rg.key_for(45.76, 4.83)]

    def test_position_still_used_by_another_spot_is_kept(self, user, other_user, fetch, run):
        first = run(lambda: f.make_spot(user, latitude=48.85, longitude=2.35))
        run(lambda: f.make_spot(other_user, latitude=48.85, longitude=2.35))
        run(first.delete)
        assert ReverseGeocode.objects.count() == 1

    def test_deleting_the_last_spot_forgets_the_position(self, user, fetch, run):
        spot = run(lambda: f.make_spot(user, latitude=48.85, longitude=2.35))
        run(spot.delete)
        assert not ReverseGeocode.objects.exists()

    def test_deleting_an_account_forgets_its_positions(self, user, fetch, run):
        run(lambda: f.make_spot(user, latitude=48.85, longitude=2.35))
        run(user.delete)
        assert not ReverseGeocode.objects.exists()

    def test_failure_never_breaks_saving_and_is_retried_on_next_trigger(self, user, other_user, monkeypatch, run):
        monkeypatch.setattr(rg, "fetch_payload", mock.Mock(side_effect=ConnectionError("down")))
        spot = run(lambda: f.make_spot(user, latitude=48.85, longitude=2.35))
        assert spot.pk and not ReverseGeocode.objects.get().is_resolved
        fetch = mock.Mock(return_value=payload("amenity", "bar"))
        monkeypatch.setattr(rg, "fetch_payload", fetch)
        run(lambda: f.make_spot(other_user, latitude=48.85, longitude=2.35))
        assert fetch.call_count == 1 and ReverseGeocode.objects.get().is_resolved

    def test_short_timeout_keeps_the_request_fast(self):
        assert rg.TIMEOUT <= 2

    def test_nothing_is_sent_for_an_unrelated_save(self, user, fetch, run):
        run(lambda: f.make_user(username="x"))
        assert fetch.call_count == 0
