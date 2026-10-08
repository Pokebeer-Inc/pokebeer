from urllib.parse import urlencode

import pytest
from django.urls import reverse

from app.models import Bar, BeerUser, Brewery, EstablishmentClaim
from tests import factories as f
from tests.helpers import assert_redirects, messages_of

pytestmark = pytest.mark.django_db


def is_authenticated(client):
    return "_auth_user_id" in client.session


class TestRegister:
    def post(self, client, **overrides):
        data = {"username": "newbie", "email": "newbie@example.test", "password1": f.PASSWORD, "password2": f.PASSWORD, **overrides}
        return client.post(reverse("register"), data)

    def test_registration_creates_contributor_and_logs_in(self, client, google_app):
        assert_redirects(self.post(client), reverse("index"))
        member = BeerUser.objects.get(username="newbie")
        assert member.is_contributor and member.check_password(f.PASSWORD)
        assert is_authenticated(client)

    def test_invalid_registration_creates_nothing(self, client, google_app, user):
        response = self.post(client, email=user.email)
        assert response.status_code == 200
        assert not BeerUser.objects.filter(username="newbie").exists()
        assert not is_authenticated(client)

    def test_authenticated_user_is_redirected_home(self, auth_client):
        assert_redirects(auth_client.get(reverse("register")), reverse("index"))


class TestLogin:
    def post(self, client, password=f.PASSWORD, next_url=None):
        url = reverse("login") + (f"?{urlencode({'next': next_url})}" if next_url else "")
        return client.post(url, {"username": "alice", "password": password})

    def test_valid_credentials_log_in(self, client, user):
        assert_redirects(self.post(client), reverse("index"))
        assert is_authenticated(client)

    def test_next_parameter_is_honoured_for_internal_urls(self, client, user):
        assert_redirects(self.post(client, next_url="/beers/"), "/beers/")

    @pytest.mark.parametrize("password", ["wrong", "", f.PASSWORD.upper()])
    def test_wrong_password_is_refused(self, client, google_app, user, password):
        assert self.post(client, password=password).status_code == 200
        assert not is_authenticated(client)

    def test_suspended_user_cannot_log_in_and_is_told_why(self, client, google_app):
        f.make_user(username="alice", is_active=False)
        response = self.post(client)
        assert response.status_code == 200
        assert not is_authenticated(client)
        assert "suspendu" in " ".join(messages_of(response))

    def test_suspension_is_not_revealed_without_the_right_password(self, client, google_app):
        f.make_user(username="alice", is_active=False)
        response = self.post(client, password="wrong")
        assert not any("suspendu" in message for message in messages_of(response))

    def test_suspension_ends_an_open_session(self, auth_client, user):
        BeerUser.objects.filter(pk=user.pk).update(is_active=False)
        response = auth_client.get(reverse("index"))
        assert response.status_code == 302 and response.url.startswith(reverse("login"))

    def test_reactivated_user_can_log_in_again(self, client, user):
        BeerUser.objects.filter(pk=user.pk).update(is_active=False)
        BeerUser.objects.filter(pk=user.pk).update(is_active=True)
        self.post(client)
        assert is_authenticated(client)

    @pytest.mark.parametrize("target", [
        "https://evil.example", "//evil.example", "///evil.example", "http:evil.example",
        "https:/evil.example", "/\\evil.example", "javascript:alert(1)",
    ])
    def test_next_parameter_cannot_redirect_to_another_site(self, client, user, target):
        assert_redirects(self.post(client, next_url=target), reverse("index"))
        assert is_authenticated(client)

    def test_absolute_url_on_the_same_host_is_allowed(self, client, user):
        assert_redirects(self.post(client, next_url="http://testserver/beers/"), "http://testserver/beers/")

    def test_authenticated_user_is_redirected_home(self, auth_client):
        assert_redirects(auth_client.get(reverse("login")), reverse("index"))

    def test_logout_ends_the_session(self, auth_client):
        assert_redirects(auth_client.get(reverse("logout")), reverse("login"))
        assert not is_authenticated(auth_client)


class TestRegisterPro:
    def data(self, **overrides):
        return {
            "user-username": "patron", "user-email": "patron@example.test", "user-password": f.PASSWORD,
            "pro-name": "Chez Patron", "pro-siret": "73282932000074", "pro-description": "Un lieu", "pro-postal_code": "44000",
            **overrides,
        }

    def test_unknown_pro_type_is_redirected_to_standard_registration(self, client):
        assert_redirects(client.get(reverse("register_pro", args=["casino"])), reverse("register"))

    @pytest.mark.parametrize("pro_type, model, role", [("brewery", Brewery, "is_brewer"), ("bar", Bar, "is_bartender")])
    def test_creates_the_account_the_establishment_and_a_pending_claim_but_no_rights(self, client, pro_type, model, role):
        assert_redirects(client.post(reverse("register_pro", args=[pro_type]), self.data()), reverse("login"))

        member = BeerUser.objects.get(username="patron")
        establishment = model.objects.get(name="Chez Patron")
        assert member.check_password(f.PASSWORD)
        # Aucun droit avant la validation de l'équipe : ni gérant, ni rôle, et le SIRET n'est pas encore rattaché à la fiche
        assert list(establishment.managers.all()) == [] and not getattr(member, role) and establishment.siret is None
        claim = EstablishmentClaim.objects.get()
        assert (claim.claimant, claim.place, claim.siret, claim.status) == (member, establishment, "73282932000074", "pending")

    def test_bar_keeps_track_of_its_creator(self, client):
        client.post(reverse("register_pro", args=["bar"]), self.data())
        assert Bar.objects.get().added_by.username == "patron"

    @pytest.mark.parametrize("overrides", [
        {"pro-siret": "123"},
        {"pro-name": ""},
        {"user-email": "alice@example.test"},
        {"user-username": "alice"},
    ], ids=["short-siret", "no-name", "dup-email", "dup-username"])
    def test_invalid_submission_creates_nothing(self, client, user, overrides):
        response = client.post(reverse("register_pro", args=["brewery"]), self.data(**overrides))
        assert response.status_code == 200
        assert not Brewery.objects.exists()
        assert BeerUser.objects.count() == 1

    def test_invalid_siret_creates_nothing(self, client):
        response = client.post(reverse("register_pro", args=["bar"]), self.data(**{"pro-siret": "12345678901234"}))
        assert response.status_code == 200 and not BeerUser.objects.filter(username="patron").exists()

    def test_database_errors_are_not_shown_to_the_visitor(self, client, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("secret internal detail")
        monkeypatch.setattr("app.models.Bar.save", boom)
        response = client.post(reverse("register_pro", args=["bar"]), self.data())
        assert "secret internal detail" not in response.content.decode() + "".join(messages_of(response))

    def test_an_existing_siret_turns_the_registration_into_a_claim_on_that_fiche(self, client):
        existing = f.make_brewery(name="Brasserie Existante", siret="73282932000074")
        client.post(reverse("register_pro", args=["brewery"]), self.data())
        assert Brewery.objects.count() == 1 and EstablishmentClaim.objects.get().brewery == existing and not existing.managers.exists()

    @pytest.mark.parametrize("password", ["1", "Ab1-xyz", "password", "12345678901", "patron2026"],
                             ids=["single-char", "too-short", "common", "numeric", "similar-to-username"])
    def test_weak_password_is_refused(self, client, password):
        response = client.post(reverse("register_pro", args=["bar"]), self.data(**{"user-password": password}))
        assert response.status_code == 200
        assert response.context["user_form"].errors["password"]
        assert not BeerUser.objects.filter(username="patron").exists()
        assert not Bar.objects.exists()
