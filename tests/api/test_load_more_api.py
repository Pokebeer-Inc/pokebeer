import pytest
from django.urls import reverse

from app.views.utils import MAX_OFFSET
from tests import factories as f

pytestmark = pytest.mark.django_db

PAGE = 10


def load(client, item_type, **params):
    return client.get(reverse("load_more_generic", args=[item_type]), params)


class TestPagination:
    @pytest.mark.parametrize("total, offset, has_more, has_html", [
        (0, 0, False, False),
        (PAGE - 1, 0, False, True),
        (PAGE, 0, True, True),
        (PAGE, PAGE, False, False),
        (PAGE + 1, PAGE, False, True),
    ])
    def test_page_boundaries(self, auth_client, total, offset, has_more, has_html):
        for _ in range(total):
            f.make_beer()
        body = load(auth_client, "unrated_beers", offset=offset).json()
        assert (body["has_more"], bool(body["html"])) == (has_more, has_html)

    def test_offset_beyond_the_end_is_empty(self, auth_client, beer):
        assert load(auth_client, "unrated_beers", offset=10_000).json() == {"html": "", "has_more": False}

    @pytest.mark.parametrize("offset", ["abc", "-1", "", "1.5", "1e3", "0x10", "²", "٣", str(MAX_OFFSET + 1), "9" * 30])
    @pytest.mark.parametrize("item_type", ["unrated_beers", "search_users"])
    def test_invalid_offset_is_rejected_gracefully(self, auth_client, item_type, offset):
        response = load(auth_client, item_type, offset=offset)
        assert response.status_code == 400
        assert response.json() == {"error": "Offset invalide"}

    @pytest.mark.parametrize("offset", ["0", " 5 ", "007", str(MAX_OFFSET)])
    def test_valid_offsets_are_accepted(self, auth_client, beer, offset):
        assert load(auth_client, "unrated_beers", offset=offset).status_code == 200

    def test_missing_offset_starts_at_the_beginning(self, auth_client, beer):
        assert auth_client.get(reverse("load_more_generic", args=["unrated_beers"])).json()["html"]


class TestItemTypes:
    @pytest.mark.parametrize("item_type", ["search_beers", "search_users", "notebook_drinks", "added_beers", "notebook_feedback"])
    def test_every_list_renders(self, auth_client, user, other_user, item_type):
        mine = f.make_beer(added_by=user)
        f.make_beer(added_by=other_user)
        f.make_drink(user, mine)
        f.make_drink(other_user, mine)
        body = load(auth_client, item_type).json()
        assert body["html"]

    def test_unknown_type_is_rejected(self, auth_client):
        response = load(auth_client, "passwords")
        assert response.status_code == 400

    def test_wishlist_source_restricts_search(self, auth_client, user, beer):
        f.make_beer(name="Autre")
        user.wishlist_beers.add(beer)
        html = load(auth_client, "search_beers", source="wishlist").json()["html"]
        assert "Test IPA" in html and "Autre" not in html

    def test_notebook_drinks_never_leak_other_users_tastings(self, auth_client, other_user):
        f.make_drink(other_user, f.make_beer(name="Secret"))
        assert load(auth_client, "notebook_drinks").json()["html"] == ""


class TestPublicLists:
    @pytest.mark.parametrize("item_type", ["public_added_beers", "public_drinks"])
    def test_username_is_required(self, auth_client, item_type):
        assert load(auth_client, item_type).status_code == 400

    @pytest.mark.parametrize("item_type", ["public_added_beers", "public_drinks"])
    def test_unknown_user_is_404(self, auth_client, item_type):
        assert load(auth_client, item_type, username="ghost").status_code == 404

    @pytest.mark.parametrize("item_type", ["public_added_beers", "public_drinks"])
    @pytest.mark.parametrize("i_block", [True, False])
    def test_blocked_profiles_are_forbidden(self, auth_client, user, other_user, item_type, i_block):
        f.block(*((user, other_user) if i_block else (other_user, user)))
        assert load(auth_client, item_type, username=other_user.username).status_code == 403

    def test_public_drinks_of_a_member(self, auth_client, other_user, beer):
        f.make_drink(other_user, beer)
        assert "Test IPA" in load(auth_client, "public_drinks", username=other_user.username).json()["html"]
