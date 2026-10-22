import pytest
from django.urls import reverse

from app.services.protection.throttle import AUTOCOMPLETE_BY_USER
from tests import factories as f
from tests.helpers import exhaust

pytestmark = pytest.mark.django_db


def search(auth_client, name, term):
    return auth_client.get(reverse(name), {"term": term}).json()


class TestSearchBrewery:
    @pytest.mark.parametrize("term", ["", "b"])
    def test_terms_shorter_than_two_chars_return_nothing(self, auth_client, brewery, term):
        assert search(auth_client, "search_brewery", term) == []

    def test_two_chars_is_enough(self, auth_client, brewery):
        assert [b["name"] for b in search(auth_client, "search_brewery", "te")] == ["Brasserie Test"]

    def test_the_place_and_the_slug_tell_two_homonyms_apart(self, auth_client):
        nantes = f.make_brewery(name="Brasserie du Coin", postal_code="44000", city="Nantes")
        lyon = f.make_brewery(name="Brasserie du Coin", postal_code="69001", city="Lyon")
        found = {b["slug"]: b["place"] for b in search(auth_client, "search_brewery", "coin")}
        assert found == {nantes.slug: "44000 Nantes", lyon.slug: "69001 Lyon"}

    def test_a_brewery_without_a_location_has_an_empty_place(self, auth_client):
        f.make_brewery(name="Brasserie Sans Lieu")
        assert search(auth_client, "search_brewery", "sans lieu")[0]["place"] == ""

    def test_results_are_capped_at_ten(self, auth_client):
        for _ in range(11):
            f.make_brewery(name=f.unique("Mousse "))
        assert len(search(auth_client, "search_brewery", "mousse")) == 10


class TestSearchBeer:
    def test_returns_name_slug_and_brewery(self, auth_client, beer):
        assert search(auth_client, "search_beer", "test") == [{"name": "Test IPA", "slug": beer.slug, "brewery": "Brasserie Test"}]

    def test_matches_without_accents(self, auth_client):
        f.make_beer(name="Bière de Noël")
        assert [b["name"] for b in search(auth_client, "search_beer", "biere de noel")] == ["Bière de Noël"]

    def test_random_slug_suffix_is_not_searchable(self, auth_client, beer):
        assert search(auth_client, "search_beer", beer.slug[-6:]) == []

    def test_deleted_beers_are_hidden(self, auth_client, beer):
        beer.is_deleted = True
        beer.save()
        assert search(auth_client, "search_beer", "test") == []

    def test_results_are_capped_at_five(self, auth_client):
        for _ in range(6):
            f.make_beer(name=f.unique("Lager "))
        assert len(search(auth_client, "search_beer", "lager")) == 5

    @pytest.mark.parametrize("term", ["", "t"])
    def test_short_terms_return_nothing(self, auth_client, beer, term):
        assert search(auth_client, "search_beer", term) == []

    def test_sql_injection_attempt_is_harmless(self, auth_client, beer):
        assert search(auth_client, "search_beer", "' OR 1=1 --") == []


class TestAutocompleteLimits:
    @pytest.mark.parametrize("name", ["search_beer", "search_brewery"])
    def test_get_only(self, auth_client, name):
        assert auth_client.post(reverse(name), {"term": "test"}).status_code == 405

    @pytest.mark.parametrize("name", ["search_beer", "search_brewery"])
    def test_throttled_per_member(self, auth_client, other_client, user, name):
        exhaust(AUTOCOMPLETE_BY_USER, user.pk)
        assert auth_client.get(reverse(name), {"term": "test"}).status_code == 429
        assert other_client.get(reverse(name), {"term": "test"}).status_code == 200

    def test_the_manager_member_search_is_throttled_too(self, auth_client, user):
        brewery = f.make_brewery(managers=[user])
        exhaust(AUTOCOMPLETE_BY_USER, user.pk)
        assert auth_client.get(reverse("api_search_users_for_manager", args=[brewery.slug]), {"q": "bob"}).status_code == 429
