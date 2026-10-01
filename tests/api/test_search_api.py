import pytest
from django.urls import reverse

from tests import factories as f

pytestmark = pytest.mark.django_db


def search(client, name, term):
    return client.get(reverse(name), {"term": term}).json()


class TestSearchBrewery:
    @pytest.mark.parametrize("term", ["", "b"])
    def test_terms_shorter_than_two_chars_return_nothing(self, client, brewery, term):
        assert search(client, "search_brewery", term) == []

    def test_two_chars_is_enough(self, client, brewery):
        assert search(client, "search_brewery", "te") == ["Brasserie Test"]

    def test_results_are_capped_at_ten(self, client):
        for _ in range(11):
            f.make_brewery(name=f.unique("Mousse "))
        assert len(search(client, "search_brewery", "mousse")) == 10


class TestSearchBeer:
    def test_returns_name_slug_and_brewery(self, client, beer):
        assert search(client, "search_beer", "test") == [{"name": "Test IPA", "slug": beer.slug, "brewery": "Brasserie Test"}]

    def test_matches_without_accents(self, client):
        f.make_beer(name="Bière de Noël")
        assert [b["name"] for b in search(client, "search_beer", "biere de noel")] == ["Bière de Noël"]

    def test_random_slug_suffix_is_not_searchable(self, client, beer):
        assert search(client, "search_beer", beer.slug[-6:]) == []

    def test_deleted_beers_are_hidden(self, client, beer):
        beer.is_deleted = True
        beer.save()
        assert search(client, "search_beer", "test") == []

    def test_results_are_capped_at_five(self, client):
        for _ in range(6):
            f.make_beer(name=f.unique("Lager "))
        assert len(search(client, "search_beer", "lager")) == 5

    @pytest.mark.parametrize("term", ["", "t"])
    def test_short_terms_return_nothing(self, client, beer, term):
        assert search(client, "search_beer", term) == []

    def test_sql_injection_attempt_is_harmless(self, client, beer):
        assert search(client, "search_beer", "' OR 1=1 --") == []
