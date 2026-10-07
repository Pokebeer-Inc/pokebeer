"""Codes-barres : validation, nettoyage des champs reçus, recherche Open Food Facts, enregistrement avec la bière."""
import io
import json
from types import SimpleNamespace
from unittest import mock

import pytest
import requests

from app.forms import BeerForm
from app.models import Beer
from app.services import beer_fields, ean, product_lookup
from tests import factories as f

LEFFE = "5410228142218"


class TestEan:
    @pytest.mark.parametrize("raw, expected", [
        (LEFFE, LEFFE), (" " + LEFFE + " ", LEFFE), ("96385074", "96385074"), ("012345678905", "0012345678905"), ("0012345678905", "0012345678905"),
    ])
    def test_valid_codes(self, raw, expected):
        assert ean.normalize(raw) == expected

    @pytest.mark.parametrize("raw", [
        "5410228142219", "12345", "", None, 5410228142218, "541022814221X", "5410228142218\n; DROP", "٥٤١٠٢٢٨١٤٢٢١٨", "../etc/passwd", "5410 2281 42218",
        "54102281422180", "1" * 100,
    ])
    def test_invalid_codes(self, raw):
        assert ean.normalize(raw) is None


class TestBeerFields:
    def test_clean_keeps_only_the_five_known_fields(self):
        cleaned = beer_fields.clean({"name": " Leffe  Blonde ", "brewery": "Inbev", "degree": "6,6", "bitterness": "20", "is_staff": True})
        assert cleaned == {"name": "Leffe Blonde", "brewery": "Inbev", "style": None, "degree": 6.6, "bitterness": 20}

    @pytest.mark.parametrize("dirty, clean", [
        ("Leffe Blonde \U0001F37A", "Leffe Blonde"), ("<b>Stout</b>", "bStout/b"), ("A​B\x00C", "ABC"), ("  \n ", None), (42, None), (None, None),
    ])
    def test_text_loses_markup_emoji_and_invisible_characters(self, dirty, clean):
        assert beer_fields.clean_text(dirty, 150) == clean

    def test_text_is_bounded(self):
        assert len(beer_fields.clean_text("x" * 1000, 150)) == 150


class FakeResponse:
    def __init__(self, status=200, body=None, raw_bytes=None):
        self.status_code = status
        payload = raw_bytes if raw_bytes is not None else json.dumps(body).encode()
        self.raw = SimpleNamespace(read=lambda n, decode_content=True: payload[:n])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


LEFFE_PRODUCT = {"status": 1, "product": {
    "product_name": "Leffe Blonde \U0001F37A", "brands": "Leffe, AB-InBev", "categories_tags": ["en:beverages", "en:beers"],
    "nutriments": {"alcohol_100g": 6.6},
}}


@pytest.fixture
def off(monkeypatch):
    get = mock.Mock(return_value=FakeResponse(body=LEFFE_PRODUCT))
    monkeypatch.setattr(product_lookup.requests, "get", get)
    return get


class TestProductLookup:
    def test_a_beer_is_returned_with_cleaned_fields(self, off):
        assert product_lookup.fetch(LEFFE) == {"name": "Leffe Blonde", "brewery": "Leffe", "style": None, "degree": 6.6, "bitterness": None}

    def test_the_request_is_safe(self, off):
        product_lookup.fetch(LEFFE)
        args, kwargs = off.call_args
        assert args[0] == f"https://world.openfoodfacts.org/api/v2/product/{LEFFE}.json"
        assert kwargs["allow_redirects"] is False and kwargs["timeout"] == 4 and kwargs["stream"] is True
        assert "Pokebeer" in kwargs["headers"]["User-Agent"] and "cookies" not in kwargs and "auth" not in kwargs

    def test_unknown_code_gives_none(self, off):
        off.return_value = FakeResponse(404, {"status": 0})
        assert product_lookup.fetch(LEFFE) is None

    @pytest.mark.parametrize("body", [
        {"status": 0}, {"status": 1, "product": {"product_name": "Chips", "categories_tags": ["en:snacks"]}},
        {"status": 1, "product": {"categories_tags": ["en:beers"]}}, {"status": 1, "product": "x"}, {"status": 1, "product": {"product_name": "X", "categories_tags": "en:beers"}},
        [], {"status": 1},
    ])
    def test_non_beers_and_incomplete_products_give_none(self, off, body):
        off.return_value = FakeResponse(200, body)
        assert product_lookup.fetch(LEFFE) is None

    @pytest.mark.parametrize("response", [
        FakeResponse(500, {}), FakeResponse(302, {}), FakeResponse(200, raw_bytes=b"not json"), FakeResponse(200, raw_bytes=b"x" * (product_lookup.MAX_RESPONSE_BYTES + 5)),
    ])
    def test_a_failing_service_is_reported_as_unavailable(self, off, response):
        off.return_value = response
        with pytest.raises(product_lookup.LookupUnavailable):
            product_lookup.fetch(LEFFE)

    @pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError(), requests.exceptions.SSLError()])
    def test_network_errors_are_reported_as_unavailable(self, off, error):
        off.side_effect = error
        with pytest.raises(product_lookup.LookupUnavailable):
            product_lookup.fetch(LEFFE)

    def test_alcohol_is_read_from_the_available_nutriment_key(self, off):
        off.return_value = FakeResponse(200, {"status": 1, "product": {"product_name": "X", "categories_tags": ["en:beers"], "nutriments": {"alcohol_value": "5,5"}}})
        assert product_lookup.fetch(LEFFE)["degree"] == 5.5

    def test_hostile_values_are_neutralised(self, off):
        off.return_value = FakeResponse(200, {"status": 1, "product": {
            "product_name": "<script>alert(1)</script>", "brands": ["x"], "categories_tags": ["en:beers"], "nutriments": {"alcohol_100g": 9999},
        }})
        assert product_lookup.fetch(LEFFE) == {"name": "scriptalert(1)/script", "brewery": None, "style": None, "degree": None, "bitterness": None}


@pytest.mark.django_db
class TestBeerFormEan:
    def data(self, **extra):
        return {"beer-name": "Leffe Blonde", "beer-brewery_name": "Inbev", "beer-degree": "6.6", **extra}

    def form(self, user, **extra):
        return BeerForm(self.data(**extra), prefix="beer", user=user)

    def test_a_scanned_code_is_stored_with_the_new_beer(self, user):
        form = self.form(user, **{"beer-ean": LEFFE})
        assert form.is_valid()
        beer = form.save(user=user)
        assert Beer.objects.get(pk=beer.pk).ean == LEFFE

    @pytest.mark.parametrize("bad", ["5410228142219", "abc", "<script>", "1" * 50, ""])
    def test_an_invalid_code_is_ignored_not_stored(self, user, bad):
        form = self.form(user, **{"beer-ean": bad})
        assert form.is_valid() and form.save(user=user).ean is None

    def test_a_code_already_in_the_catalogue_is_ignored_and_does_not_block_the_beer(self, user):
        existing = f.make_beer(name="Autre")
        Beer.objects.filter(pk=existing.pk).update(ean=LEFFE)
        form = self.form(user, **{"beer-ean": LEFFE})
        assert form.is_valid() and form.save(user=user).ean is None

    def test_a_deleted_beer_frees_its_code(self, user):
        gone = f.make_beer(name="Disparue", is_deleted=True)
        Beer.objects.filter(pk=gone.pk).update(ean=LEFFE)
        form = self.form(user, **{"beer-ean": LEFFE})
        assert form.is_valid()
        assert form.save(user=user).ean == LEFFE

    def test_the_code_cannot_be_changed_when_editing(self, user):
        beer = f.make_beer(name="Existante")
        Beer.objects.filter(pk=beer.pk).update(ean=LEFFE)
        beer.refresh_from_db()  # comme la vue de modification, qui charge la bière depuis la base
        form = BeerForm({"name": "Existante", "brewery_name": beer.brewery_id.name, "degree": "5.0", "ean": "96385074"}, instance=beer, user=user)
        assert "ean" not in form.fields
        assert form.is_valid()
        form.save()
        assert Beer.objects.get(pk=beer.pk).ean == LEFFE
