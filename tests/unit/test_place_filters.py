"""Filtres et tri des brasseries et des bars : ville lue dans l'adresse, vérifiés, style brassé, tri par nom ou ajout."""
import pytest

from app.models import Bar, Brewery
from app.services import place_filters
from app.services.places import BAR, BREWERY
from tests import factories as f

pytestmark = pytest.mark.django_db


def names(model, kind, **params):
    return sorted(p.name for p in place_filters.apply(model.objects.all(), params, kind))


class TestCities:
    def test_city_is_read_after_the_postal_code(self):
        f.make_bar(name="A", address="2 Quai de la Fosse, 44000 Nantes")
        f.make_bar(name="B", address="5 Rue du Port, 29900 Concarneau, France")
        f.make_bar(name="D", address="Sans code postal")
        f.make_bar(name="E")
        assert place_filters.cities(Bar) == ["Concarneau", "Nantes"]

    def test_the_same_city_is_listed_once_whatever_accents_and_case(self):
        f.make_bar(name="A", address="1 rue A, 91000 Évry")
        f.make_bar(name="B", address="2 rue B, 91000 EVRY")
        assert place_filters.cities(Bar) == ["Évry"]

    def test_cities_are_per_kind(self):
        f.make_brewery(name="Brasserie", address="1 rue A, 59000 Lille")
        assert place_filters.cities(Bar) == [] and place_filters.cities(Brewery) == ["Lille"]

    def test_filtering_by_city_ignores_accents_and_case(self):
        f.make_bar(name="Nantais", address="2 Quai de la Fosse, 44000 Nantes")
        f.make_bar(name="Lyonnais", address="1 rue A, 69000 Lyon")
        f.make_bar(name="Evryen", address="1 rue A, 91000 Évry")
        assert names(Bar, BAR, city="nantes") == ["Nantais"]
        assert names(Bar, BAR, city="EVRY") == ["Evryen"]
        assert names(Bar, BAR, city="  Lyon ") == ["Lyonnais"]
        assert names(Bar, BAR, city="Paris") == []


class TestOtherFilters:
    def test_verified_only(self):
        f.make_bar(name="Vérifié", is_verified=True)
        f.make_bar(name="Autre")
        assert names(Bar, BAR, verified="1") == ["Vérifié"]

    def test_breweries_by_style_brewed_ignoring_deleted_beers(self):
        ipa, stout, ghost = f.make_brewery(name="IPA House"), f.make_brewery(name="Stout House"), f.make_brewery(name="Ghost")
        f.make_beer(brewery=ipa, style="West Coast IPA")
        f.make_beer(brewery=stout, style="Stout")
        f.make_beer(brewery=ghost, style="IPA", is_deleted=True)
        assert names(Brewery, BREWERY, style="ipa") == ["IPA House"]

    def test_style_does_not_apply_to_bars(self):
        f.make_bar(name="Bar")
        assert names(Bar, BAR, style="IPA") == ["Bar"]

    def test_filters_combine(self):
        f.make_bar(name="Les deux", address="1 rue A, 69000 Lyon", is_verified=True)
        f.make_bar(name="Lyon seul", address="1 rue A, 69000 Lyon")
        f.make_bar(name="Vérifié seul", address="1 rue A, 75000 Paris", is_verified=True)
        assert names(Bar, BAR, city="Lyon", verified="1") == ["Les deux"]

    @pytest.mark.parametrize("hostile", ["'; DROP TABLE app_bar; --", "%", "_", "\\", "a" * 5000, "<script>"])
    def test_hostile_values_are_harmless(self, hostile):
        f.make_bar(name="Bar", address="1 rue A, 69000 Lyon")
        assert names(Bar, BAR, city=hostile, style=hostile) == []
        assert Bar.objects.count() == 1

    def test_is_filtered(self):
        assert not place_filters.is_filtered({}) and not place_filters.is_filtered({"q": "x", "tab": "bars"})
        assert place_filters.is_filtered({"city": "Lyon"}) and place_filters.is_filtered({"verified": "1"})


class TestSort:
    @pytest.fixture
    def bars(self):
        return [f.make_bar(name="Charlie"), f.make_bar(name="Alpha"), f.make_bar(name="Bravo")]

    def ordered(self, sort, default=("name",)):
        queryset = place_filters.apply(Bar.objects.all(), {"sort": sort}, BAR).order_by(*place_filters.ordering({"sort": sort}, default))
        return [bar.name for bar in queryset]

    @pytest.mark.parametrize("sort, expected", [
        ("name_asc", ["Alpha", "Bravo", "Charlie"]),
        ("name_desc", ["Charlie", "Bravo", "Alpha"]),
        ("date_asc", ["Charlie", "Alpha", "Bravo"]),
        ("date_desc", ["Bravo", "Alpha", "Charlie"]),
    ])
    def test_each_sort(self, bars, sort, expected):
        assert self.ordered(sort) == expected

    @pytest.mark.parametrize("sort", ["", None, "nope", "name; DROP TABLE app_bar", "-id"])
    def test_unknown_values_fall_back_to_the_default_order(self, bars, sort):
        assert place_filters.ordering({"sort": sort}, ("name",)) == ("name",)
        assert self.ordered(sort) == ["Alpha", "Bravo", "Charlie"]

    def test_a_chosen_sort_replaces_the_relevance_order(self):
        assert place_filters.ordering({"sort": "name_desc"}, ("search_rank", "name")) == ("-name", "id")

    def test_sort_counts_as_an_active_filter(self):
        assert place_filters.is_filtered({"sort": "name_asc"})
