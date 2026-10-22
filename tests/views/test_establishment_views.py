from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from app.models import BeerUser, ManagerInvitation, Notification, UserBlock
from app.services.establishments import team
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

    def test_place_page_shows_a_visible_directions_button_beside_the_address(self, auth_client, geocoder):
        bar = f.make_bar(name="Le Troubadour", street="1 rue de la Paix", postal_code="69001", city="Lyon")
        html = auth_client.get(reverse("bar_detail", args=[bar.slug])).content.decode()
        assert html.count("https://www.google.com/maps/dir/?") == 2  # l'adresse et le bouton mènent au même endroit
        assert "Y aller" in html and "https://www.google.com/maps/search" not in html

    def test_place_page_without_address_has_no_directions_button(self, auth_client):
        html = auth_client.get(reverse("bar_detail", args=[f.make_bar().slug])).content.decode()
        assert "Y aller" not in html

    def test_bar_page(self, auth_client):
        bar = f.make_bar(name="Le Comptoir")
        assert auth_client.get(reverse("bar_detail", args=[bar.slug])).context["bar"] == bar

    def test_numeric_primary_key_does_not_resolve(self, auth_client, brewery):
        assert auth_client.get(reverse("brewery_detail", args=[str(brewery.pk)])).status_code == 404

    @pytest.mark.parametrize("name", ["brewery_detail", "bar_detail", "edit_brewery", "edit_bar"])
    def test_unknown_establishment_is_404(self, auth_client, name):
        assert auth_client.get(reverse(name, args=["unknown-slug"])).status_code == 404


class TestEditBrewery:
    def data(self, **overrides):
        return {"name": "Nouveau nom", "description": "Nouvelle description", "street": "1 Rue de Rennes", "postal_code": "44000", **overrides}

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

    def test_picture_is_reencoded_replaced_and_removed(self, auth_client, managed_brewery, django_capture_on_commit_callbacks):
        url = reverse("edit_brewery", args=[managed_brewery.slug])
        auth_client.post(url, {**self.data(), "image": f.make_image_upload()})
        managed_brewery.refresh_from_db()
        first, storage = managed_brewery.image.name, managed_brewery.image.storage
        assert first.startswith("breweries/") and first.endswith(".webp")
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(url, {**self.data(), "remove_image": "on"})
        managed_brewery.refresh_from_db()
        assert not managed_brewery.image and not storage.exists(first)

    def test_non_image_file_is_refused(self, auth_client, managed_brewery):
        from django.core.files.uploadedfile import SimpleUploadedFile
        response = auth_client.post(reverse("edit_brewery", args=[managed_brewery.slug]), {**self.data(), "image": SimpleUploadedFile("a.png", b"nope")})
        assert response.status_code == 200
        managed_brewery.refresh_from_db()
        assert not managed_brewery.image

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

    def test_manager_invites_a_collaborator_who_gets_no_role_before_accepting(self, auth_client, managed_brewery, other_user):
        self.add(auth_client, managed_brewery, other_user)
        assert not managed_brewery.managers.filter(pk=other_user.pk).exists()
        assert not BeerUser.objects.get(pk=other_user.pk).is_brewer
        invitation = ManagerInvitation.objects.get()
        assert (invitation.invitee, invitation.brewery, invitation.status) == (other_user, managed_brewery, "pending")
        assert Notification.objects.get().notif_type == "manager_invited"

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


class TestInvitations:
    @pytest.fixture
    def invitation(self, auth_client, managed_brewery, other_user):
        auth_client.post(reverse("add_brewery_manager", args=[managed_brewery.slug]), {"username": other_user.username})
        return ManagerInvitation.objects.get()

    def respond(self, client, invitation, answer):
        return client.post(reverse("respond_invitation", args=[invitation.slug]), {"answer": answer})

    def test_the_invitee_sees_it_on_the_profile(self, other_client, invitation):
        html = other_client.get(reverse("account")).content.decode()
        assert reverse("respond_invitation", args=[invitation.slug]) in html

    def test_accepting_grants_the_team_and_the_role(self, other_client, user, other_user, managed_brewery, invitation):
        response = self.respond(other_client, invitation, "accept")
        assert_redirects(response, reverse("brewery_detail", args=[managed_brewery.slug]))
        assert managed_brewery.managers.filter(pk=other_user.pk).exists() and BeerUser.objects.get(pk=other_user.pk).is_brewer
        invitation.refresh_from_db()
        assert invitation.status == "accepted"
        assert Notification.objects.get(notif_type="manager_invitation_accepted").recipient == user
        assert not Notification.objects.filter(notif_type="manager_invited").exists()

    def test_declining_grants_nothing(self, other_client, user, other_user, managed_brewery, invitation):
        self.respond(other_client, invitation, "decline")
        assert not managed_brewery.managers.filter(pk=other_user.pk).exists() and not BeerUser.objects.get(pk=other_user.pk).is_brewer
        invitation.refresh_from_db()
        assert invitation.status == "declined"
        assert Notification.objects.get(notif_type="manager_invitation_declined").recipient == user

    def test_only_the_invitee_can_answer(self, client_for, managed_brewery, invitation):
        intruder = f.make_user()
        self.respond(client_for(intruder), invitation, "accept")
        assert not managed_brewery.managers.filter(pk=intruder.pk).exists()
        invitation.refresh_from_db()
        assert invitation.status == "pending"

    def test_an_answer_is_given_once(self, other_client, other_user, managed_brewery, invitation):
        self.respond(other_client, invitation, "decline")
        self.respond(other_client, invitation, "accept")
        assert not managed_brewery.managers.filter(pk=other_user.pk).exists()

    def test_it_expires(self, other_client, other_user, managed_brewery, invitation):
        ManagerInvitation.objects.update(created_at=timezone.now() - team.INVITATION_VALIDITY - timedelta(minutes=1))
        self.respond(other_client, invitation, "accept")
        assert not managed_brewery.managers.filter(pk=other_user.pk).exists()

    def test_it_dies_with_the_inviter_access(self, other_client, user, other_user, managed_brewery, invitation):
        managed_brewery.managers.remove(user)
        self.respond(other_client, invitation, "accept")
        assert not managed_brewery.managers.filter(pk=other_user.pk).exists()
        invitation.refresh_from_db()
        assert invitation.status == "cancelled"

    def test_a_manager_can_withdraw_it(self, auth_client, other_client, other_user, managed_brewery, invitation):
        auth_client.post(reverse("cancel_invitation", args=[invitation.slug]))
        invitation.refresh_from_db()
        assert invitation.status == "cancelled" and not Notification.objects.filter(notif_type="manager_invited").exists()
        self.respond(other_client, invitation, "accept")
        assert not managed_brewery.managers.filter(pk=other_user.pk).exists()

    def test_an_outsider_cannot_withdraw_it(self, client_for, invitation):
        client_for(f.make_user()).post(reverse("cancel_invitation", args=[invitation.slug]))
        invitation.refresh_from_db()
        assert invitation.status == "pending"

    def test_no_duplicate_while_pending(self, auth_client, managed_brewery, other_user, invitation):
        auth_client.post(reverse("add_brewery_manager", args=[managed_brewery.slug]), {"username": other_user.username})
        assert ManagerInvitation.objects.count() == 1

    def test_blocked_members_cannot_be_invited_nor_found(self, auth_client, user, managed_brewery):
        blocker = f.make_user(username="blocker")
        UserBlock.objects.create(blocker=blocker, blocked=user)
        auth_client.post(reverse("add_brewery_manager", args=[managed_brewery.slug]), {"username": blocker.username})
        assert not ManagerInvitation.objects.exists()
        found = auth_client.get(reverse("api_search_users_for_manager", args=[managed_brewery.slug]), {"q": "blocker"}).json()["users"]
        assert found == []

    def test_pending_invitees_are_not_proposed_again(self, auth_client, managed_brewery, other_user, invitation):
        found = auth_client.get(reverse("api_search_users_for_manager", args=[managed_brewery.slug]), {"q": other_user.username[:3]}).json()["users"]
        assert other_user.username not in [u["username"] for u in found]

    def test_the_manager_sees_pending_invitations(self, auth_client, managed_brewery, invitation):
        html = auth_client.get(reverse("brewery_detail", args=[managed_brewery.slug])).content.decode()
        assert reverse("cancel_invitation", args=[invitation.slug]) in html


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
        assert users[0]["avatar_url"].startswith("data:image/svg+xml,")

    def test_results_are_capped_at_ten(self, auth_client, managed_brewery):
        for _ in range(11):
            f.make_user(username=f.unique("brewer_"))
        assert len(self.search(auth_client, managed_brewery, "brewer_").json()["users"]) == 10


class TestBarManagement:
    """Un bar offre les mêmes fonctions de gestion qu'une brasserie."""

    @pytest.fixture
    def managed_bar(self, user):
        return f.make_bar(name="Le Comptoir", managers=[user])

    def test_manager_sees_the_team(self, auth_client, user, managed_bar):
        context = auth_client.get(reverse("bar_detail", args=[managed_bar.slug])).context
        assert context["is_manager"] and list(context["current_managers"]) == [user]

    def test_visitor_does_not_see_the_team(self, auth_client):
        bar = f.make_bar(name="Le Zinc")
        context = auth_client.get(reverse("bar_detail", args=[bar.slug])).context
        assert not context["is_manager"] and not context["current_managers"]

    def test_non_manager_cannot_edit(self, auth_client):
        bar = f.make_bar(name="Le Zinc")
        response = auth_client.post(reverse("edit_bar", args=[bar.slug]), {"name": "Piraté", "description": "x"})
        assert_redirects(response, reverse("bar_detail", args=[bar.slug]))
        bar.refresh_from_db()
        assert bar.name == "Le Zinc"

    def test_manager_edits_and_other_managers_are_notified(self, auth_client, managed_bar, other_user, geocoder):
        managed_bar.managers.add(other_user)
        response = auth_client.post(
            reverse("edit_bar", args=[managed_bar.slug]),
            {"name": "Nouveau nom", "description": "Nouvelle description", "street": "1 Rue de Rennes", "postal_code": "44000"},
        )
        managed_bar.refresh_from_db()
        assert_redirects(response, reverse("bar_detail", args=[managed_bar.slug]))
        assert (managed_bar.name, managed_bar.latitude) == ("Nouveau nom", 48.8566)
        notification = Notification.objects.get()
        assert (notification.recipient, notification.notif_type, notification.bar) == (other_user, "place_updated", managed_bar)

    def test_invalid_data_is_refused(self, auth_client, managed_bar):
        response = auth_client.post(reverse("edit_bar", args=[managed_bar.slug]), {"name": "", "website": "not a url"})
        assert response.status_code == 200
        managed_bar.refresh_from_db()
        assert managed_bar.name == "Le Comptoir"

    def test_manager_adds_then_removes_a_collaborator(self, auth_client, other_client, managed_bar, other_user):
        auth_client.post(reverse("add_bar_manager", args=[managed_bar.slug]), {"username": other_user.username})
        assert not BeerUser.objects.get(pk=other_user.pk).is_bartender
        invitation = ManagerInvitation.objects.get(bar=managed_bar)
        other_client.post(reverse("respond_invitation", args=[invitation.slug]), {"answer": "accept"})
        assert managed_bar.managers.filter(pk=other_user.pk).exists()
        assert BeerUser.objects.get(pk=other_user.pk).is_bartender

        auth_client.post(reverse("remove_bar_manager", args=[managed_bar.slug, other_user.username]))
        assert not BeerUser.objects.get(pk=other_user.pk).is_bartender
        assert Notification.objects.get(notif_type="manager_removed").text_content == "Le Comptoir"

    def test_non_manager_cannot_add_or_remove(self, other_client, user, other_user):
        bar = f.make_bar(name="Le Zinc", managers=[user])
        other_client.post(reverse("add_bar_manager", args=[bar.slug]), {"username": other_user.username})
        other_client.post(reverse("remove_bar_manager", args=[bar.slug, user.username]))
        assert list(bar.managers.all()) == [user]

    def test_manager_cannot_remove_himself(self, auth_client, user, managed_bar):
        auth_client.post(reverse("remove_bar_manager", args=[managed_bar.slug, user.username]))
        assert managed_bar.managers.filter(pk=user.pk).exists()

    def test_search_is_reserved_to_managers(self, auth_client, managed_bar, other_user):
        url = reverse("api_search_users_for_bar_manager", args=[managed_bar.slug])
        users = auth_client.get(url, {"q": "bob"}).json()["users"]
        assert [u["username"] for u in users] == ["bobby"]
        stranger = f.make_bar(name="Le Zinc")
        forbidden = auth_client.get(reverse("api_search_users_for_bar_manager", args=[stranger.slug]), {"q": "bob"})
        assert forbidden.status_code == 403
