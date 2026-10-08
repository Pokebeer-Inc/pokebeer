"""Adresse découpée (rue, code postal, ville), annuaire des communes, appel prudent d'un service extérieur."""
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest import mock

import pytest
import requests
from django.apps import apps
from django.urls import reverse
from django.utils import timezone

from app.forms import BarEditForm, BreweryEditForm, BreweryProForm
from app.models import Bar, Brewery, PostalCode
from app.services import address, postal_codes, upstream
from app.services.throttle import POSTAL_LOOKUP_BY_IP, Rule
from tests import factories as f

pytestmark = pytest.mark.django_db


class TestAddressParts:
    @pytest.mark.parametrize("full, expected", [
        ("5 Rue du Port, 29900 Concarneau", ("5 Rue du Port", "29900", "Concarneau")),
        ("5 rue du Port 29900 Concarneau", ("5 rue du Port", "29900", "Concarneau")),
        ("12 Quai du Port, 13002 Marseille, France", ("12 Quai du Port", "13002", "Marseille")),
        ("  8   Quai Saint-Antoine ,  69002   Lyon ", ("8 Quai Saint-Antoine", "69002", "Lyon")),
        ("44000 Nantes", ("", "44000", "Nantes")),
        ("Rennes", ("Rennes", "", "")),
        ("", ("", "", "")), (None, ("", "", "")),
        ("3 Grand Place, 59000 Lille Cedex 9", ("3 Grand Place", "59000", "Lille Cedex 9")),
    ])
    def test_parse(self, full, expected):
        assert address.parse(full) == expected

    @pytest.mark.parametrize("parts, expected", [
        (("5 Rue du Port", "29900", "Concarneau"), "5 Rue du Port, 29900 Concarneau"), (("", "44000", "Nantes"), "44000 Nantes"),
        (("5 Rue du Port", "", ""), "5 Rue du Port"), (("", "", ""), ""), (("5 Rue", "29900", ""), "5 Rue, 29900"),
    ])
    def test_compose(self, parts, expected):
        assert address.compose(*parts) == expected

    def test_what_is_composed_can_be_parsed_back(self):
        parts = ("20 Rue de la République", "38000", "Grenoble")
        assert address.parse(address.compose(*parts)) == parts

    def test_hostile_text_is_kept_as_text_and_bounded(self):
        street, postal, city = address.parse("<script>alert(1)</script> 44000 Nantes" + " x" * 5000)
        assert postal == "" or len(city) < 20000


class TestModels:
    def test_the_full_address_can_be_read_and_written_as_text(self):
        brewery = f.make_brewery(name="Brasserie Test", address="5 Rue du Port, 29900 Concarneau")
        assert (brewery.street, brewery.postal_code, brewery.city) == ("5 Rue du Port", "29900", "Concarneau") and brewery.address == "5 Rue du Port, 29900 Concarneau"

    def test_the_parts_are_stored_in_their_own_columns(self):
        bar = f.make_bar(street="1 Rue A", postal_code="44000", city="Nantes")
        assert Bar.objects.filter(postal_code="44000", city="Nantes").get() == bar

    def test_geocoding_needs_a_street(self, geocoder):
        f.make_brewery(name="Sans rue", postal_code="44000", city="Nantes")
        assert geocoder.call_count == 0 and Brewery.objects.get(name="Sans rue").latitude is None
        located = f.make_brewery(name="Avec rue", street="1 Rue A", postal_code="44000", city="Nantes")
        assert geocoder.call_count == 1 and located.latitude == 48.8566
        assert "1 Rue A, 44000 Nantes" in str(geocoder.call_args)

    def test_completing_the_street_later_places_the_fiche(self, geocoder):
        brewery = f.make_brewery(name="Sans rue", postal_code="44000", city="Nantes")
        brewery.street = "2 Quai de la Fosse"
        brewery.save()
        assert Brewery.objects.get(pk=brewery.pk).latitude == 48.8566

    def test_changing_nothing_does_not_geocode_again(self, geocoder):
        brewery = f.make_brewery(name="X", street="1 Rue A", postal_code="44000", city="Nantes")
        calls = geocoder.call_count
        brewery.description = "Nouvelle description"
        brewery.save()
        assert geocoder.call_count == calls

    def test_the_old_column_is_gone_and_split_functions_round_trip(self):
        brewery = f.make_brewery(name="Migrée", address="8 Quai Saint-Antoine, 69002 Lyon")
        assert "address" not in {field.name for field in Brewery._meta.get_fields()}
        migration = import_module("app.migrations.0073_split_address_postal_codes")
        assert migration.address_service.parse("8 Quai Saint-Antoine, 69002 Lyon") == (brewery.street, brewery.postal_code, brewery.city)


class TestPostalCodeDirectory:
    @pytest.fixture
    def fetch(self, monkeypatch):
        calls = mock.Mock(side_effect=lambda code: {"44100": ["Nantes", "Saint-Herblain"], "44000": ["Nantes"]}.get(code, []))
        monkeypatch.setattr(postal_codes, "_fetch", calls)
        return calls

    def test_a_code_is_fetched_once_then_remembered(self, fetch):
        assert postal_codes.communes("44000") == ["Nantes"] and postal_codes.communes("44000") == ["Nantes"]
        assert fetch.call_count == 1 and PostalCode.objects.filter(code="44000").count() == 1

    def test_several_communes_are_all_remembered(self, fetch):
        assert postal_codes.communes("44100") == ["Nantes", "Saint-Herblain"] and postal_codes.communes("44100") == ["Nantes", "Saint-Herblain"]
        assert fetch.call_count == 1

    def test_an_unknown_code_is_remembered_too(self, fetch):
        assert postal_codes.communes("99999") == [] and postal_codes.communes("99999") == []
        assert fetch.call_count == 1 and PostalCode.objects.get(code="99999").city == ""

    def test_an_old_answer_is_refreshed(self, fetch):
        postal_codes.communes("44000")
        PostalCode.objects.update(fetched_at=timezone.now() - postal_codes.MAX_AGE - timedelta(days=1))
        postal_codes.communes("44000")
        assert fetch.call_count == 2 and PostalCode.objects.filter(code="44000").count() == 1

    @pytest.mark.parametrize("bad", ["", "4400", "440000", "abcde", "44 00", "٤٤٠٠٠", None, 44000])
    def test_badly_formed_codes_never_reach_the_directory(self, fetch, bad):
        assert postal_codes.communes(bad) == [] and fetch.call_count == 0

    def test_an_outage_is_reported_when_nothing_is_remembered(self, monkeypatch):
        monkeypatch.setattr(postal_codes, "_fetch", mock.Mock(side_effect=upstream.UpstreamUnavailable))
        with pytest.raises(upstream.UpstreamUnavailable):
            postal_codes.communes("44000")
        assert PostalCode.objects.count() == 0

    def test_resolution(self, fetch):
        assert postal_codes.resolve("44000") == postal_codes.Resolution("44000", "Nantes", True)
        assert postal_codes.resolve("44000", "  nantes ") == postal_codes.Resolution("44000", "Nantes", True)
        assert postal_codes.resolve("", "") == postal_codes.Resolution("", "", False)

    @pytest.mark.parametrize("code, city, field", [
        ("4400", "", "postal_code"), ("99999", "", "postal_code"), ("", "Nantes", "postal_code"),
        ("44000", "Lyon", "city"), ("44100", "", "city"), ("44100", "Paris", "city"),
    ])
    def test_refusals_name_the_field(self, fetch, code, city, field):
        with pytest.raises(postal_codes.PostalCodeError) as raised:
            postal_codes.resolve(code, city)
        assert raised.value.field == field and str(raised.value)

    def test_several_communes_require_a_choice_and_accept_one_of_them(self, fetch):
        assert postal_codes.resolve("44100", "saint-herblain").city == "Saint-Herblain"

    def test_an_outage_never_blocks_the_input(self, monkeypatch):
        monkeypatch.setattr(postal_codes, "_fetch", mock.Mock(side_effect=upstream.UpstreamUnavailable))
        assert postal_codes.resolve("44000", "Nantes") == postal_codes.Resolution("44000", "Nantes", False)
        assert postal_codes.resolve("44000") == postal_codes.Resolution("44000", "", False)


class TestForms:
    def pro(self, **extra):
        return {"name": "Brasserie X", "siret": "73282932000074", "description": "Desc", **extra}

    def test_the_city_comes_from_the_postal_code(self):
        form = BreweryProForm(data=self.pro(postal_code="44000"))
        assert form.is_valid() and (form.cleaned_data["postal_code"], form.cleaned_data["city"]) == ("44000", "Nantes")

    def test_the_postal_code_is_required_for_a_pro(self):
        assert "postal_code" in BreweryProForm(data=self.pro()).errors

    @pytest.mark.parametrize("extra, field", [({"postal_code": "9999"}, "postal_code"), ({"postal_code": "01234"}, "postal_code"), ({"postal_code": "44000", "city": "Paris"}, "city"), ({"postal_code": "44100"}, "city")])
    def test_wrong_locations_are_refused(self, extra, field):
        assert field in BreweryProForm(data=self.pro(**extra)).errors

    def test_the_street_is_optional_for_now(self):
        assert BreweryProForm(data=self.pro(postal_code="44000")).is_valid()

    @pytest.mark.parametrize("form_class", [BreweryEditForm, BarEditForm])
    def test_edit_forms_check_the_city_too(self, form_class):
        base = {"name": "Nom", "description": "D", "street": "1 Rue A"}
        assert form_class(data={**base, "postal_code": "44000"}).is_valid()
        assert "city" in form_class(data={**base, "postal_code": "44000", "city": "Lyon"}).errors
        assert form_class(data=base).is_valid()  # une fiche ancienne sans code postal reste modifiable


class TestApi:
    URL = reverse("postal_code_lookup")

    def test_it_is_open_without_login_for_the_registration_page(self, client, postal_directory):
        assert client.get(self.URL, {"code": "44000"}).json() == {"cities": ["Nantes"], "known": True, "available": True}

    def test_several_communes(self, client):
        assert client.get(self.URL, {"code": "44100"}).json()["cities"] == ["Nantes", "Saint-Herblain"]

    @pytest.mark.parametrize("code", ["", "4400", "abcde", "44000'; DROP TABLE x;--", "9" * 50])
    def test_bad_input_gives_an_empty_answer(self, client, code):
        assert client.get(self.URL, {"code": code}).json() == {"cities": [], "known": False, "available": True}

    def test_an_unknown_code_is_not_known(self, client):
        assert client.get(self.URL, {"code": "99999"}).json() == {"cities": [], "known": False, "available": True}

    def test_an_outage_is_reported_without_details(self, client, monkeypatch):
        monkeypatch.setattr(postal_codes, "_fetch", mock.Mock(side_effect=upstream.UpstreamUnavailable("secret detail")))
        response = client.get(self.URL, {"code": "44000"})
        assert response.json() == {"cities": [], "known": False, "available": False} and "secret" not in response.content.decode()

    def test_it_is_throttled_per_address(self, client, monkeypatch):
        monkeypatch.setattr("app.views.api_views.POSTAL_LOOKUP_BY_IP", Rule("postal-ip", 2, POSTAL_LOOKUP_BY_IP.window))
        assert [client.get(self.URL, {"code": "44000"}).status_code for _ in range(3)] == [200, 200, 429]

    def test_get_only(self, client):
        assert client.post(self.URL).status_code == 405

    def test_the_form_widgets_carry_the_lookup_url(self):
        html = str(BreweryProForm()["postal_code"])
        assert f'data-postal-url="{self.URL}"' in html and 'inputmode="numeric"' in html and 'pattern="\\d{5}"' in html


class FakeResponse:
    def __init__(self, status=200, payload=b"[]"):
        self.status_code = status
        self.raw = SimpleNamespace(read=lambda n, decode_content=True: payload[:n])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestUpstream:
    @pytest.fixture
    def get(self, monkeypatch):
        mocked = mock.Mock(return_value=FakeResponse(payload=b'{"ok": true}'))
        monkeypatch.setattr(upstream.requests, "get", mocked)
        return mocked

    def test_a_json_answer_is_returned(self, get):
        assert upstream.get_json("https://example.test/x", {"a": 1}) == {"ok": True}

    def test_the_call_is_cautious(self, get):
        upstream.get_json("https://example.test/x", {"a": 1})
        kwargs = get.call_args.kwargs
        assert kwargs["allow_redirects"] is False and kwargs["stream"] is True and kwargs["timeout"] == 4 and kwargs["params"] == {"a": 1}
        assert "Pokebeer" in kwargs["headers"]["User-Agent"] and not {"cookies", "auth", "data", "json"} & set(kwargs)

    def test_404_means_not_found(self, get):
        get.return_value = FakeResponse(404)
        assert upstream.get_json("https://example.test/x") is None

    @pytest.mark.parametrize("response", [FakeResponse(500), FakeResponse(302), FakeResponse(403), FakeResponse(200, b"not json"), FakeResponse(200, b"x" * (upstream.MAX_RESPONSE_BYTES + 5))])
    def test_every_other_failure_is_an_outage(self, get, response):
        get.return_value = response
        with pytest.raises(upstream.UpstreamUnavailable):
            upstream.get_json("https://example.test/x")

    @pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError(), requests.exceptions.SSLError(), requests.exceptions.TooManyRedirects()])
    def test_network_errors_are_outages(self, get, error):
        get.side_effect = error
        with pytest.raises(upstream.UpstreamUnavailable):
            upstream.get_json("https://example.test/x")
