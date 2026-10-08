from types import SimpleNamespace
from unittest import mock

import pytest
from django.core.cache import cache

from app.services import upstream
from app.services.chat import geocoding, places
from app.services.chat.geo import Coordinates
from app.services.chat.tools import FindPlacesTool, build_tools
from tests import factories as f

PARIS = Coordinates(48.86, 2.35)


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()


def locate(place, lat, lng):
    """Place l'établissement sans passer par le géocodage réseau de `save`."""
    type(place).objects.filter(pk=place.pk).update(latitude=lat, longitude=lng)
    return place


def osm(*elements):
    return {"elements": list(elements)}


def pub(name, lat, lon, **tags):
    return {"type": "node", "id": 1, "lat": lat, "lon": lon, "tags": {"amenity": "pub", "name": name, **tags}}


@pytest.fixture
def overpass(monkeypatch):
    get = mock.Mock(return_value=osm())
    monkeypatch.setattr(upstream, "get_json", get)
    return get


@pytest.mark.django_db
class TestFindNearby:
    def test_database_places_are_filtered_by_radius_and_ranked_by_distance(self, overpass):
        locate(f.make_bar("Loin"), 48.90, 2.35)
        locate(f.make_bar("Près"), 48.861, 2.351)
        locate(f.make_bar("Trop loin"), 45.76, 4.84)
        f.make_bar("Sans position")

        result = places.find_nearby(PARIS, "bar", radius_km=10)

        assert [place.name for place in result.places] == ["Près", "Loin"]
        assert result.places[0].source == "pokebeer" and result.places[0].link.startswith("/")

    def test_kind_filter(self, overpass):
        locate(f.make_bar("Le Bar"), 48.861, 2.351)
        locate(f.make_brewery("La Brasserie"), 48.862, 2.352)
        assert [p.name for p in places.find_nearby(PARIS, "brewery").places] == ["La Brasserie"]
        assert {p.name for p in places.find_nearby(PARIS, "any").places} == {"Le Bar", "La Brasserie"}

    def test_openstreetmap_places_are_cleaned_and_linked_to_the_map(self, overpass):
        overpass.return_value = osm(pub("Pub <b>Irlandais</b>​", 48.861, 2.351, **{"addr:street": "rue Xyz", "addr:housenumber": "4"}))
        (place,) = places.find_nearby(PARIS, "bar").places
        assert place.name == "Pub b Irlandais /b" and place.address == "4 rue Xyz"
        assert place.link.startswith("https://www.openstreetmap.org/?mlat=48.86100&mlon=2.35100")

    def test_keyword_match_comes_first_even_when_farther(self, overpass):
        overpass.return_value = osm(pub("Proche", 48.861, 2.351), pub("Plus loin", 48.88, 2.35, brewery="Guinness;Kilkenny"))
        result = places.find_nearby(PARIS, "bar", "guinness")
        assert [(p.name, p.keyword_match) for p in result.places] == [("Plus loin", True), ("Proche", False)]

    def test_database_place_wins_over_the_same_place_in_openstreetmap(self, overpass):
        locate(f.make_bar("Le Dubliner"), 48.861, 2.351, )
        overpass.return_value = osm(pub("Dubliner", 48.8611, 2.3511), pub("Autre pub", 48.87, 2.36))
        result = places.find_nearby(PARIS, "bar")
        assert [(p.name, p.source) for p in result.places] == [("Le Dubliner", "pokebeer"), ("Autre pub", "openstreetmap")]

    def test_an_unavailable_source_degrades_the_result_instead_of_failing(self, overpass):
        locate(f.make_bar("Le Bar"), 48.861, 2.351)
        overpass.side_effect = upstream.UpstreamUnavailable
        result = places.find_nearby(PARIS, "bar")
        assert [p.name for p in result.places] == ["Le Bar"] and result.complete is False

    def test_results_are_capped_and_radius_is_bounded(self, overpass):
        overpass.return_value = osm(*[pub(f"Pub {i}", 48.86 + i / 1000, 2.35) for i in range(20)])
        assert len(places.find_nearby(PARIS, "bar", radius_km=9999).places) == places.MAX_RESULTS
        assert "around:25000" in overpass.call_args.kwargs["params"]["data"]

    def test_openstreetmap_answers_are_cached(self, overpass):
        places.find_nearby(PARIS, "bar")
        places.find_nearby(PARIS, "bar")
        assert overpass.call_count == 1

    def test_malformed_elements_are_skipped(self, overpass):
        overpass.return_value = osm("x", {"tags": {"name": "Sans point"}}, {"lat": 1, "lon": 2, "tags": {}}, pub("Bon", 48.861, 2.351))
        assert [p.name for p in places.find_nearby(PARIS, "bar").places] == ["Bon"]


@pytest.mark.django_db
class TestOverpassQuery:
    @pytest.mark.parametrize("keyword, expected", [('guinness"; out;', "guinness out"), ("IPA", "IPA"), ("<script>", "script"), ("l'été", "l'été")])
    def test_keyword_cannot_inject_query_syntax(self, keyword, expected):
        assert places.clean_keyword(keyword) == expected

    def test_keyword_is_not_part_of_the_query_itself(self, overpass):
        places.find_nearby(PARIS, "bar", 'x"]; node(1); out;')
        assert "node(1)" not in overpass.call_args.kwargs["params"]["data"]


@pytest.mark.django_db
class TestFindPlacesTool:
    def test_returns_places_with_confirmation_flags(self, overpass):
        overpass.return_value = osm(pub("Pub", 48.861, 2.351, brewery="Guinness"))
        result = FindPlacesTool(PARIS).run({"keyword": "guinness", "kind": "bar"})
        assert result["complete"] is True and result["searched_around"] == "la position du membre"
        assert result["places"][0]["confirmed_match"] is True and result["places"][0]["name"] == "Pub"

    def test_unknown_kind_and_bad_radius_fall_back_to_defaults(self, overpass):
        FindPlacesTool(PARIS).run({"kind": "rm -rf", "radius_km": "beaucoup"})
        assert "around:3000" in overpass.call_args.kwargs["params"]["data"]

    def test_without_any_position_the_model_is_told_to_ask(self, overpass):
        assert "localisation" in FindPlacesTool(None).run({})["error"]
        overpass.assert_not_called()

    def test_a_named_place_is_geocoded_and_replaces_the_device_position(self, monkeypatch, overpass):
        monkeypatch.setattr(upstream, "get_json", mock.Mock(side_effect=[[{"lat": "53.35", "lon": "-6.26"}], osm()]))
        FindPlacesTool(PARIS).run({"place_name": "Dublin"})
        assert "53.35" in upstream.get_json.call_args.kwargs["params"]["data"]

    def test_declaration_is_exposed_by_the_registry(self):
        (tool,) = build_tools(PARIS).values()
        assert tool.declaration().name == "find_places"


class TestGeocoding:
    def test_result_is_cached_even_when_nothing_is_found(self, monkeypatch):
        cache.clear()
        get = mock.Mock(return_value=[])
        monkeypatch.setattr(upstream, "get_json", get)
        assert geocoding.geocode("Nullepart") is None and geocoding.geocode("nullepart") is None
        assert get.call_count == 1

    @pytest.mark.parametrize("answer", [None, {}, ["x"], [{"lat": "a", "lon": "b"}]])
    def test_unusable_answers(self, monkeypatch, answer):
        cache.clear()
        monkeypatch.setattr(upstream, "get_json", mock.Mock(return_value=answer))
        assert geocoding.geocode("Ville") is None

    def test_outage_and_empty_names(self, monkeypatch):
        cache.clear()
        monkeypatch.setattr(upstream, "get_json", mock.Mock(side_effect=upstream.UpstreamUnavailable))
        assert geocoding.geocode("Ville") is None and geocoding.geocode("   ") is None
