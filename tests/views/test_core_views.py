from datetime import date

import pytest
from django.urls import reverse

from tests import factories as f

pytestmark = pytest.mark.django_db

HOME_LIMIT = 10


class TestHome:
    def test_unrated_beers_exclude_mine_and_deleted_and_are_capped(self, auth_client, user, beer):
        for _ in range(HOME_LIMIT + 1):
            f.make_beer()
        f.make_beer(is_deleted=True)
        f.make_drink(user, beer)

        unrated = auth_client.get(reverse("index")).context["unrated_beers"]

        assert len(unrated) == HOME_LIMIT
        assert beer not in unrated

    def test_rankings_only_contain_rated_active_beers(self, auth_client, other_user):
        best, good, deleted = f.make_beer(name="Best"), f.make_beer(name="Good"), f.make_beer(is_deleted=True)
        f.make_beer(name="Unrated")
        f.make_drink(other_user, best, note=9)
        f.make_drink(other_user, good, note=6, date=date(2000, 1, 1))
        f.make_drink(other_user, deleted, note=10)

        context = auth_client.get(reverse("index")).context

        assert [b.name for b in context["top"]] == ["Best", "Good"]
        assert [b.name for b in context["topMonth"]] == ["Best"]

    def test_rankings_are_capped_at_ten(self, auth_client, other_user):
        for _ in range(HOME_LIMIT + 2):
            f.make_drink(other_user, note=5)
        assert len(auth_client.get(reverse("index")).context["top"]) == HOME_LIMIT

    def test_wishlist_flags_only_displayed_beers(self, auth_client, user, beer):
        user.wishlist_beers.add(beer)
        assert auth_client.get(reverse("index")).context["wishlist_beer_ids"] == [beer.id]

    def test_page_sets_csrf_cookie_for_javascript(self, auth_client):
        assert "csrftoken" in auth_client.get(reverse("index")).cookies

    def test_service_role_key_never_reaches_the_browser(self, auth_client, settings):
        settings.SUPABASE_SERVICE_ROLE_KEY = "service-role-secret-value"
        assert b"service-role-secret-value" not in auth_client.get(reverse("index")).content


class TestAllBeers:
    def test_beers_tab_by_default_with_split_styles(self, auth_client):
        f.make_beer(style="Stout, IPA")
        f.make_beer(style="IPA")
        f.make_beer(style="Porter", is_deleted=True)
        context = auth_client.get(reverse("all_beers")).context
        assert (context["active_tab"], context["styles"]) == ("bieres", ["IPA", "Stout"])

    @pytest.mark.parametrize("params", [{"uq": "bob"}, {"tab": "membres"}])
    def test_members_tab(self, auth_client, params):
        assert auth_client.get(reverse("all_beers"), params).context["active_tab"] == "membres"

    def test_first_page_is_capped_at_ten(self, auth_client):
        for _ in range(HOME_LIMIT + 1):
            f.make_beer()
        assert len(auth_client.get(reverse("all_beers")).context["beers"]) == HOME_LIMIT

    def test_hostile_search_input_is_escaped(self, auth_client):
        payload = "<script>alert(1)</script>"
        content = auth_client.get(reverse("all_beers"), {"q": payload, "uq": payload}).content
        assert payload.encode() not in content
