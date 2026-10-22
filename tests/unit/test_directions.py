from urllib.parse import parse_qs, urlparse

import pytest

from app.models import Bar
from app.services.establishments import directions
from tests import factories as f

pytestmark = pytest.mark.django_db


def query(url):
    return parse_qs(urlparse(url).query)


class TestLinks:
    def test_uses_the_name_and_address_so_the_map_recognises_the_place(self, geocoder):
        bar = f.make_bar(name="Le Troubadour", street="1 rue de la Paix", postal_code="69001", city="Lyon")
        links = directions.links(bar)
        assert urlparse(links["google"]).netloc == "www.google.com" and urlparse(links["apple"]).netloc == "maps.apple.com"
        assert query(links["google"])["destination"] == [f"Le Troubadour, {bar.address}"]
        assert query(links["apple"])["daddr"] == [f"Le Troubadour, {bar.address}"]

    def test_falls_back_to_coordinates_without_an_address(self):
        bar = Bar(name="Sans adresse", latitude=45.764, longitude=4.8357)  # non enregistré : pas de géocodage
        assert query(directions.links(bar)["google"])["destination"] == ["45.764000,4.835700"]

    def test_nothing_without_address_or_coordinates(self):
        assert directions.links(f.make_bar()) is None

    def test_special_characters_cannot_change_the_link(self, geocoder):
        bar = f.make_bar(name="Bar & Co #1 ?x=1", street="2 rue \"X\"", postal_code="69001", city="Lyon")
        links = directions.links(bar)
        for url, key in ((links["google"], "destination"), (links["apple"], "daddr")):
            assert " " not in url and "&x=1" not in url and query(url)[key] == [f"{bar.name}, {bar.address}"]
        assert query(links["google"])["api"] == ["1"]
