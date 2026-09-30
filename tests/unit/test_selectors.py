from decimal import Decimal

import pytest
from django.test import RequestFactory

from app.views.services.selectors import get_filtered_beers, get_filtered_notebook_drinks, get_filtered_users
from tests import factories as f

pytestmark = pytest.mark.django_db


def request_for(user, **params):
    request = RequestFactory().get("/", params)
    request.user = user
    return request


def names(queryset):
    return [item.name for item in queryset]


@pytest.fixture
def degree_beers(brewery):
    return {d: f.make_beer(name=f"Deg {d}", brewery=brewery, degree=Decimal(d)) for d in ("4.9", "5.0", "8.0", "8.1")}


@pytest.fixture
def ibu_beers(brewery):
    return {ibu: f.make_beer(name=f"Ibu {ibu}", brewery=brewery, bitterness=ibu) for ibu in (19, 20, 50, 51)}


class TestFilteredBeers:
    @pytest.mark.parametrize("value, expected", [
        ("light", ["Deg 4.9"]),
        ("regular", ["Deg 5.0", "Deg 8.0"]),
        ("strong", ["Deg 8.1"]),
        ("unknown", ["Deg 4.9", "Deg 5.0", "Deg 8.0", "Deg 8.1"]),
    ])
    def test_degree_ranges_boundaries(self, user, degree_beers, value, expected):
        assert names(get_filtered_beers(request_for(user, degree=value, sort="name_asc"))) == expected

    @pytest.mark.parametrize("value, expected", [
        ("low", ["Ibu 19"]), ("medium", ["Ibu 20", "Ibu 50"]), ("high", ["Ibu 51"]),
    ])
    def test_ibu_ranges_boundaries(self, user, ibu_beers, value, expected):
        assert names(get_filtered_beers(request_for(user, ibu=value, sort="name_asc"))) == expected

    @pytest.mark.parametrize("sort, expected", [
        ("name_asc", ["Deg 4.9", "Deg 5.0", "Deg 8.0", "Deg 8.1"]),
        ("name_desc", ["Deg 8.1", "Deg 8.0", "Deg 5.0", "Deg 4.9"]),
        ("degree_desc", ["Deg 8.1", "Deg 8.0", "Deg 5.0", "Deg 4.9"]),
        ("degree_asc", ["Deg 4.9", "Deg 5.0", "Deg 8.0", "Deg 8.1"]),
        ("date_asc", ["Deg 4.9", "Deg 5.0", "Deg 8.0", "Deg 8.1"]),
        ("date_desc", ["Deg 8.1", "Deg 8.0", "Deg 5.0", "Deg 4.9"]),
    ])
    def test_sort_orders(self, user, degree_beers, sort, expected):
        assert names(get_filtered_beers(request_for(user, sort=sort))) == expected

    def test_default_sort_puts_rated_beers_last(self, user, degree_beers):
        f.make_drink(user, degree_beers["8.1"])
        assert names(get_filtered_beers(request_for(user))) == ["Deg 8.0", "Deg 5.0", "Deg 4.9", "Deg 8.1"]

    def test_search_matches_beer_or_brewery_name_case_insensitively(self, user):
        f.make_beer(name="Chouffe", brewery=f.make_brewery(name="Achouffe"))
        f.make_beer(name="Autre", brewery=f.make_brewery(name="CHOUF Brewing"))
        f.make_beer(name="Sans rapport")
        assert sorted(names(get_filtered_beers(request_for(user, q="chouf")))) == ["Autre", "Chouffe"]

    def test_style_filter_matches_any_listed_style(self, user):
        f.make_beer(name="Mixte", style="Stout, Ipa")
        f.make_beer(name="Lager", style="Lager")
        assert names(get_filtered_beers(request_for(user, style="ipa"))) == ["Mixte"]

    def test_deleted_beers_are_hidden(self, user):
        f.make_beer(name="Visible")
        f.make_beer(name="Cachée", is_deleted=True)
        assert names(get_filtered_beers(request_for(user))) == ["Visible"]

    @pytest.mark.parametrize("direction", ["i_block", "blocks_me"])
    def test_beers_added_by_blocked_users_are_hidden(self, user, other_user, direction):
        f.make_beer(name="Du bloqué", added_by=other_user)
        blocker, blocked = (user, other_user) if direction == "i_block" else (other_user, user)
        f.block(blocker, blocked)
        assert names(get_filtered_beers(request_for(user))) == []

    def test_sql_wildcards_are_matched_literally(self, user):
        f.make_beer(name="Bière 100%")
        f.make_beer(name="Bière 100 pur")
        assert names(get_filtered_beers(request_for(user, q="100%"))) == ["Bière 100%"]


class TestFilteredUsers:
    def test_without_query_only_contributors_are_listed_newest_first(self, user):
        early, late, _silent = f.make_user(), f.make_user(), f.make_user()
        f.make_beer(added_by=early)
        f.make_beer(added_by=late)
        assert list(get_filtered_users(request_for(user))) == [late, early]

    def test_query_filters_usernames_and_excludes_self(self, user):
        match = f.make_user(username="alice_fan")
        assert list(get_filtered_users(request_for(user, uq="ALICE"))) == [match]

    def test_blocked_users_are_hidden(self, user, other_user):
        f.block(other_user, user)
        assert list(get_filtered_users(request_for(user, uq="bob"))) == []

    def test_user_is_listed_once_whatever_his_number_of_beers(self, user, other_user):
        for _ in range(3):
            f.make_beer(added_by=other_user)
        assert list(get_filtered_users(request_for(user))) == [other_user]


class TestFilteredNotebookDrinks:
    @pytest.fixture
    def notes(self, user):
        return {note: f.make_drink(user, f.make_beer(name=f"Note {note:02d}"), note=note) for note in (0, 5, 10)}

    def test_only_own_drinks_are_returned(self, user, other_user, notes):
        f.make_drink(other_user)
        assert get_filtered_notebook_drinks(request_for(user)).count() == 3

    @pytest.mark.parametrize("params, expected", [
        ({"rating_min": "5"}, [5, 10]),
        ({"rating_max": "5"}, [0, 5]),
        ({"rating_min": "5", "rating_max": "5"}, [5]),
        ({"rating_min": "0", "rating_max": "10"}, [0, 5, 10]),
        ({"rating_min": "-1"}, [0, 5, 10]),
        ({"rating_min": "abc", "rating_max": "1e3"}, [0, 5, 10]),
    ])
    def test_rating_bounds_are_inclusive_and_invalid_values_ignored(self, user, notes, params, expected):
        drinks = get_filtered_notebook_drinks(request_for(user, sort="note_asc", **params))
        assert [d.note for d in drinks] == expected

    def test_notebook_filter(self, user, notes):
        notebook = f.make_notebook(user, drinks=[notes[5]])
        assert list(get_filtered_notebook_drinks(request_for(user, notebook_id=str(notebook.id)))) == [notes[5]]

    def test_non_numeric_notebook_id_is_ignored(self, user, notes):
        assert get_filtered_notebook_drinks(request_for(user, notebook_id="1 OR 1=1")).count() == 3

    @pytest.mark.parametrize("sort, expected", [("note_desc", [10, 5, 0]), ("name_desc", [10, 5, 0]), ("name_asc", [0, 5, 10])])
    def test_sorts(self, user, notes, sort, expected):
        assert [d.note for d in get_filtered_notebook_drinks(request_for(user, sort=sort))] == expected
