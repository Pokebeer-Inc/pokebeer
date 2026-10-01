import pytest
from django.urls import reverse

from app.models import BeerUser, Notification
from tests import factories as f
from tests.helpers import assert_redirects

pytestmark = pytest.mark.django_db


@pytest.fixture
def managed_brewery(brewery, user):
    brewery.managers.add(user)
    return brewery


class TestDetailPages:
    def test_brewery_lists_its_active_beers(self, auth_client, brewery, beer):
        f.make_beer(brewery=brewery, is_deleted=True)
        context = auth_client.get(reverse("brewery_detail", args=[brewery.slug])).context
        assert list(context["beers"]) == [beer]
        assert not context["is_manager"]

    def test_manager_sees_the_team(self, auth_client, user, managed_brewery):
        context = auth_client.get(reverse("brewery_detail", args=[managed_brewery.slug])).context
        assert context["is_manager"] and list(context["current_managers"]) == [user]

    def test_bar_page(self, auth_client):
        bar = f.make_bar(name="Le Comptoir")
        assert auth_client.get(reverse("bar_detail", args=[bar.slug])).context["bar"] == bar

    def test_numeric_primary_key_does_not_resolve(self, auth_client, brewery):
        assert auth_client.get(reverse("brewery_detail", args=[str(brewery.pk)])).status_code == 404

    @pytest.mark.parametrize("name", ["brewery_detail", "bar_detail", "edit_brewery"])
    def test_unknown_establishment_is_404(self, auth_client, name):
        assert auth_client.get(reverse(name, args=["unknown-slug"])).status_code == 404


class TestEditBrewery:
    def data(self, **overrides):
        return {"name": "Nouveau nom", "description": "Nouvelle description", "address": "Rennes", **overrides}

    def test_non_manager_is_refused(self, auth_client, brewery):
        response = auth_client.post(reverse("edit_brewery", args=[brewery.slug]), self.data())
        assert_redirects(response, reverse("brewery_detail", args=[brewery.slug]))
        brewery.refresh_from_db()
        assert brewery.name == "Brasserie Test"

    def test_manager_edits_and_other_managers_are_notified(self, auth_client, managed_brewery, other_user, geocoder):
        managed_brewery.managers.add(other_user)
        auth_client.post(reverse("edit_brewery", args=[managed_brewery.slug]), self.data())
        managed_brewery.refresh_from_db()
        assert (managed_brewery.name, managed_brewery.latitude) == ("Nouveau nom", 48.8566)
        assert list(Notification.objects.values_list("recipient", "notif_type")) == [(other_user.id, "place_updated")]

    @pytest.mark.parametrize("field, value", [("name", ""), ("website", "not a url"), ("email", "nope"), ("name", "x" * 151)])
    def test_invalid_data_is_refused(self, auth_client, managed_brewery, field, value):
        response = auth_client.post(reverse("edit_brewery", args=[managed_brewery.slug]), self.data(**{field: value}))
        assert response.status_code == 200
        managed_brewery.refresh_from_db()
        assert managed_brewery.name == "Brasserie Test"


class TestManagers:
    def add(self, client, brewery, member):
        return client.post(reverse("add_brewery_manager", args=[brewery.slug]), {"username": member.username})

    def remove(self, client, brewery, member):
        return client.post(reverse("remove_brewery_manager", args=[brewery.slug, member.username]))

    def test_manager_adds_a_collaborator(self, auth_client, managed_brewery, other_user):
        self.add(auth_client, managed_brewery, other_user)
        assert managed_brewery.managers.filter(pk=other_user.pk).exists()
        assert BeerUser.objects.get(pk=other_user.pk).is_brewer
        assert Notification.objects.get().notif_type == "manager_added"

    def test_non_manager_cannot_add(self, other_client, brewery, other_user):
        self.add(other_client, brewery, other_user)
        assert not brewery.managers.exists()

    def test_get_does_not_add(self, auth_client, managed_brewery, other_user):
        auth_client.get(reverse("add_brewery_manager", args=[managed_brewery.slug]), {"username": other_user.username})
        assert managed_brewery.managers.count() == 1

    def test_manager_removes_a_collaborator(self, auth_client, managed_brewery, other_user):
        managed_brewery.managers.add(other_user)
        self.remove(auth_client, managed_brewery, other_user)
        assert not BeerUser.objects.get(pk=other_user.pk).is_brewer
        notification = Notification.objects.get(notif_type="manager_removed")
        assert (notification.recipient, notification.text_content) == (other_user, "Brasserie Test")

    def test_manager_cannot_remove_himself(self, auth_client, user, managed_brewery):
        self.remove(auth_client, managed_brewery, user)
        assert managed_brewery.managers.filter(pk=user.pk).exists()

    def test_non_manager_cannot_remove(self, other_client, user, managed_brewery):
        self.remove(other_client, managed_brewery, user)
        assert managed_brewery.managers.filter(pk=user.pk).exists()


class TestManagerSearchApi:
    def search(self, client, brewery, query):
        return client.get(reverse("api_search_users_for_manager", args=[brewery.slug]), {"q": query})

    def test_non_manager_is_forbidden(self, auth_client, brewery):
        assert self.search(auth_client, brewery, "bob").status_code == 403

    @pytest.mark.parametrize("query", ["", "b", " b "])
    def test_short_queries_return_nothing(self, auth_client, managed_brewery, other_user, query):
        assert self.search(auth_client, managed_brewery, query).json() == {"users": []}

    def test_existing_managers_are_excluded(self, auth_client, managed_brewery, other_user):
        assert self.search(auth_client, managed_brewery, "ali").json() == {"users": []}
        users = self.search(auth_client, managed_brewery, "bob").json()["users"]
        assert [u["username"] for u in users] == ["bobby"]
        assert "id" not in users[0]
        assert users[0]["avatar_url"].startswith("https://ui-avatars.com/")

    def test_results_are_capped_at_ten(self, auth_client, managed_brewery):
        for _ in range(11):
            f.make_user(username=f.unique("brewer_"))
        assert len(self.search(auth_client, managed_brewery, "brewer_").json()["users"]) == 10
