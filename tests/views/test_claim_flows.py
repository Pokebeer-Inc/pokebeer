"""Parcours complets : inscription d'un gérant, bouton « Revendiquer », file d'administration, homonymes à l'ajout d'une bière."""
import pytest
from django.core import mail
from django.urls import reverse

from django.template.loader import render_to_string

from app.forms import BeerForm
from app.models import Beer, BeerUser, Brewery, EstablishmentClaim, Notification
from app.services.catalog import catalog_matching as cm
from app.services.establishments import claims, siret_registry
from tests import factories as f
from tests.unit.test_claims import SIRET

pytestmark = pytest.mark.django_db

REGISTER = {"brewery": reverse("register_pro", args=["brewery"]), "bar": reverse("register_pro", args=["bar"])}


def pro_data(**overrides):
    return {
        "user-username": "patron", "user-email": "patron@example.test", "user-password": f.PASSWORD,
        "pro-name": "Brasserie du Coin", "pro-siret": SIRET, "pro-description": "Un lieu", "pro-postal_code": "44000", **overrides,
    }


@pytest.fixture
def coin():
    return f.make_brewery(name="Brasserie du Coin", postal_code="44000", city="Nantes")


class TestProRegistration:
    def test_a_lookalike_fiche_in_the_same_city_asks_which_one_is_theirs(self, client, coin):
        response = client.post(REGISTER["brewery"], pro_data(**{"pro-name": "Microbrasserie du Coin"}))
        html = response.content.decode()
        assert response.status_code == 200 and "data-claim-choice" in html and "Brasserie du Coin" in html and 'name="pro-claim_choice"' in html
        assert not BeerUser.objects.filter(username="patron").exists() and Brewery.objects.count() == 1

    def test_choosing_the_existing_fiche_creates_the_account_and_a_pending_claim_on_it(self, client, coin):
        client.post(REGISTER["brewery"], pro_data(**{"pro-name": "Microbrasserie du Coin", "pro-claim_choice": f"existing:{coin.slug}"}))
        claim = EstablishmentClaim.objects.get()
        assert claim.brewery == coin and claim.claimant.username == "patron" and Brewery.objects.count() == 1 and not coin.managers.exists()

    def test_confirming_creates_a_new_fiche_and_still_a_pending_claim(self, client, coin):
        token = cm.find_brewery("Microbrasserie du Coin", "44000", "Nantes").token
        client.post(REGISTER["brewery"], pro_data(**{"pro-name": "Microbrasserie du Coin", "pro-claim_choice": f"new:{token}"}))
        assert Brewery.objects.count() == 2 and EstablishmentClaim.objects.get().brewery.name == "Microbrasserie du Coin"

    def test_a_forged_choice_creates_nothing(self, client, coin):
        client.post(REGISTER["brewery"], pro_data(**{"pro-name": "Microbrasserie du Coin", "pro-claim_choice": "new:forged"}))
        assert not BeerUser.objects.filter(username="patron").exists() and not EstablishmentClaim.objects.exists()

    def test_the_same_name_in_another_city_is_just_another_establishment(self, client, coin):
        client.post(REGISTER["brewery"], pro_data(**{"pro-postal_code": "69001"}))
        place = Brewery.objects.get(city="Lyon")
        assert place.name == "Brasserie du Coin" and EstablishmentClaim.objects.get().brewery == place

    def test_an_unknown_siret_stops_the_registration(self, client, siret_directory):
        siret_directory[SIRET] = siret_registry.SiretCheck(siret=SIRET)
        response = client.post(REGISTER["brewery"], pro_data())
        assert response.status_code == 200 and "existe pas dans l" in response.content.decode()
        assert not BeerUser.objects.filter(username="patron").exists() and not Brewery.objects.exists()

    def test_the_siret_stays_on_the_claim_until_approval(self, client):
        """Poser le SIRET dès l'inscription permettrait de « réserver » le SIRET de quelqu'un d'autre."""
        client.post(REGISTER["brewery"], pro_data())
        assert Brewery.objects.get().siret is None and EstablishmentClaim.objects.get().siret == SIRET

    def test_squatting_a_real_siret_does_not_block_its_owner(self, client, other_client, user):
        client.post(REGISTER["brewery"], pro_data(**{"pro-name": "Usurpateur"}))
        form = {**pro_data(**{"user-username": "vrai", "user-email": "vrai@example.test", "pro-name": "Vraie Brasserie", "pro-postal_code": "69001"})}
        client.post(REGISTER["brewery"], form)
        assert BeerUser.objects.filter(username="vrai").exists() and EstablishmentClaim.objects.count() == 2

    def test_nobody_gets_rights_at_registration(self, client):
        client.post(REGISTER["bar"], pro_data(**{"pro-name": "Le Zinc"}))
        member = BeerUser.objects.get(username="patron")
        assert not member.managed_bars.exists() and not member.is_bartender and not member.is_brewer

    def test_the_member_is_told_what_happens_next(self, client, google_app):
        response = client.post(REGISTER["brewery"], pro_data(), follow=True)
        assert "en cours d&#x27;examen" in response.content.decode() and any("bien reçue" in m.subject for m in mail.outbox)

    def test_an_existing_siret_leads_to_a_claim_on_its_fiche_even_if_managed(self, client, other_user):
        held = f.make_brewery(name="Déjà gérée", siret=SIRET, managers=[other_user])
        client.post(REGISTER["brewery"], pro_data(**{"pro-name": "Un autre nom", "pro-postal_code": "75010"}))
        assert EstablishmentClaim.objects.get().brewery == held and Notification.objects.filter(recipient=other_user, notif_type="claim_received").exists()

    def test_the_page_explains_the_validation(self, client):
        html = client.get(REGISTER["brewery"]).content.decode()
        assert "vérifie ensuite votre SIRET" in html and 'name="pro-postal_code"' in html and "cities-pro" in html and "postal_code.js" in html


class TestClaimButton:
    def url(self, place):
        return reverse("claim_brewery" if isinstance(place, Brewery) else "claim_bar", args=[place.slug])

    def test_the_fiche_page_offers_the_claim_to_a_non_manager(self, auth_client, coin):
        assert self.url(coin) in auth_client.get(reverse("brewery_detail", args=[coin.slug])).content.decode()

    def test_a_manager_does_not_see_it(self, auth_client, user, coin):
        coin.managers.add(user)
        assert self.url(coin) not in auth_client.get(reverse("brewery_detail", args=[coin.slug])).content.decode()

    def test_bars_too(self, auth_client):
        bar = f.make_bar(name="Le Zinc")
        assert self.url(bar) in auth_client.get(reverse("bar_detail", args=[bar.slug])).content.decode()

    def test_the_form_page(self, auth_client, coin):
        html = auth_client.get(self.url(coin)).content.decode()
        assert "Revendiquer cette fiche" in html and 'name="siret"' in html and "droits de gestion ne sont accordés qu'après cette validation" in html

    def test_sending_a_claim(self, auth_client, user, coin):
        response = auth_client.post(self.url(coin), {"siret": SIRET, "message": "Bonjour"})
        assert response.status_code == 302 and EstablishmentClaim.objects.get().claimant == user and not coin.managers.exists()

    def test_a_pending_claim_replaces_the_button(self, auth_client, coin):
        auth_client.post(self.url(coin), {"siret": SIRET})
        html = auth_client.get(reverse("brewery_detail", args=[coin.slug])).content.decode()
        assert "Demande de gestion en cours" in html and self.url(coin) not in html

    @pytest.mark.parametrize("siret, expected", [("123", "SIRET"), ("", "obligatoire")])
    def test_bad_input_is_explained(self, auth_client, coin, siret, expected):
        response = auth_client.post(self.url(coin), {"siret": siret})
        assert response.status_code == 200 and expected in response.content.decode() and not EstablishmentClaim.objects.exists()

    def test_the_registry_error_is_shown_on_the_siret_field(self, auth_client, coin, siret_directory):
        siret_directory[SIRET] = siret_registry.SiretCheck(siret=SIRET)
        html = auth_client.post(self.url(coin), {"siret": SIRET}).content.decode()
        assert "existe pas dans l" in html and not EstablishmentClaim.objects.exists()

    def test_a_manager_is_sent_back(self, auth_client, user, coin):
        coin.managers.add(user)
        assert auth_client.post(self.url(coin), {"siret": SIRET}).status_code == 302 and not EstablishmentClaim.objects.exists()

    def test_login_is_required(self, client, coin):
        assert client.get(self.url(coin)).status_code == 302 and client.post(self.url(coin), {"siret": SIRET}).status_code == 302

    def test_csrf_is_enforced(self, user, coin):
        from django.test import Client
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(user)
        assert strict.post(self.url(coin), {"siret": SIRET}).status_code == 403

    def test_the_account_page_shows_and_cancels_pending_claims(self, auth_client, user, coin):
        auth_client.post(self.url(coin), {"siret": SIRET})
        assert "Demande de gestion en cours d'examen" in auth_client.get(reverse("account")).content.decode()
        claim = EstablishmentClaim.objects.get()
        assert auth_client.post(reverse("cancel_claim", args=[claim.pk])).status_code == 302
        claim.refresh_from_db()
        assert claim.status == "cancelled" and "Demande de gestion en cours d'examen" not in auth_client.get(reverse("account")).content.decode()

    def test_nobody_can_cancel_someone_elses_claim(self, other_client, user, coin):
        claim = claims.open_claim(user, claims.BREWERY if hasattr(claims, "BREWERY") else __import__("app.services.establishments.places", fromlist=["BREWERY"]).BREWERY, coin, SIRET)
        assert other_client.post(reverse("cancel_claim", args=[claim.pk])).status_code == 404
        claim.refresh_from_db()
        assert claim.status == "pending"

    def test_cancelling_requires_post(self, auth_client):
        assert auth_client.get(reverse("cancel_claim", args=[1])).status_code == 405


class TestAdminQueue:
    LIST = "admin:app_establishmentclaim_changelist"

    @pytest.fixture
    def claim(self, user, coin):
        from app.services.establishments.places import BREWERY
        return claims.open_claim(user, BREWERY, coin, SIRET, "Gérante depuis 2019")

    def act(self, claim, name):
        return reverse("admin:app_establishmentclaim_action", args=[claim.pk, name])

    def test_the_queue_opens_on_pending_claims(self, client_for, superuser, claim):
        response = client_for(superuser).get(reverse(self.LIST))
        assert response.status_code == 302 and "status__exact=pending" in response.url
        assert "patron" not in client_for(superuser).get(response.url).content.decode()  # le demandeur est « alice » dans cette fixture
        assert claim.claimant.username in client_for(superuser).get(response.url).content.decode()

    def test_the_detail_shows_the_registry_checks_and_both_actions(self, client_for, superuser, claim):
        html = client_for(superuser).get(reverse("admin:app_establishmentclaim_change", args=[claim.pk])).content.decode()
        assert "Contrôle automatique du SIRET" in html and "Accepter la demande" in html and "Motif du refus" in html and "Gérante depuis 2019" in html
        assert self.act(claim, "approve") in html and "csrfmiddlewaretoken" in html

    def test_approving(self, client_for, superuser, claim, coin, user):
        client_for(superuser).post(self.act(claim, "approve"))
        coin.refresh_from_db()
        assert list(coin.managers.all()) == [user] and coin.siret == SIRET and user.is_brewer

    def test_rejecting_needs_a_reason(self, client_for, superuser, claim, coin):
        client = client_for(superuser)
        client.post(self.act(claim, "reject"), {"reason": ""})
        claim.refresh_from_db()
        assert claim.status == "pending"
        client.post(self.act(claim, "reject"), {"reason": "Pas le bon établissement"})
        claim.refresh_from_db()
        assert claim.status == "rejected" and claim.reason == "Pas le bon établissement" and not coin.managers.exists()

    def test_a_decided_claim_shows_no_actions(self, client_for, superuser, claim):
        claims.approve(claim, superuser)
        html = client_for(superuser).get(reverse("admin:app_establishmentclaim_change", args=[claim.pk])).content.decode()
        assert "Accepter la demande" not in html and "Accepté" in html or "Acceptée" in html

    @pytest.mark.parametrize("action", ["approve", "reject"])
    def test_moderators_cannot_decide(self, client_for, staff, claim, action):
        assert client_for(staff).post(self.act(claim, action), {"reason": "x"}).status_code in (302, 403, 404)
        claim.refresh_from_db()
        assert claim.status == "pending"

    def test_decisions_are_post_only_and_actions_are_known(self, client_for, superuser, claim):
        client = client_for(superuser)
        assert client.get(self.act(claim, "approve")).status_code == 405
        assert client.post(self.act(claim, "explode")).status_code == 404
        claim.refresh_from_db()
        assert claim.status == "pending"

    def test_csrf_protects_the_decisions(self, superuser, claim):
        from django.test import Client
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(superuser)
        assert strict.post(self.act(claim, "approve")).status_code == 403
        claim.refresh_from_db()
        assert claim.status == "pending"

    def test_the_claims_cannot_be_edited_or_deleted_in_the_admin(self, client_for, superuser, claim):
        client = client_for(superuser)
        assert client.get(reverse("admin:app_establishmentclaim_add")).status_code == 403
        assert client.post(reverse("admin:app_establishmentclaim_delete", args=[claim.pk]), {"post": "yes"}).status_code == 403
        assert EstablishmentClaim.objects.filter(pk=claim.pk).exists()

    def test_the_sidebar_counts_pending_claims(self, claim):
        from app.admin.pending import pending_claims_count
        assert pending_claims_count() == 1


class TestHomonymsInTheBeerForm:
    """Le lieu de la brasserie n'est demandé qu'au formulaire complet (gérant de bar, staff) : le membre, lui, peut ne pas connaître la brasserie."""

    def form(self, user, brewery="Brasserie du Coin", postal="", **extra):
        data = {"beer-name": "Nouvelle Blonde", "beer-brewery_name": brewery, "beer-degree": "6.5", "beer-brewery_postal_code": postal, **extra}
        return BeerForm(data, prefix="beer", user=user)

    def add(self, user, **kwargs):
        form = self.form(user, **kwargs)
        if form.is_valid():
            form.save(user=user)
        return form

    def test_without_a_postal_code_the_known_brewery_is_reused_and_the_member_is_invited_to_give_one(self, auth_client, user, coin):
        self.add(user)
        assert Beer.objects.get().brewery == coin
        html = auth_client.get(reverse("check_catalog"), {"name": "Autre", "brewery": "Brasserie du Coin"}).json()["html"]
        assert "Indiquez le code postal de votre brasserie" in html

    def test_the_same_postal_code_reuses_the_brewery(self, user, coin):
        self.add(user, postal="44000")
        assert Beer.objects.get().brewery == coin and Brewery.objects.count() == 1

    def test_another_postal_code_creates_a_homonym_in_its_own_city(self, user, coin):
        self.add(user, postal="69001")
        beer = Beer.objects.get()
        assert beer.brewery != coin and (beer.brewery.name, beer.brewery.postal_code, beer.brewery.city) == ("Brasserie du Coin", "69001", "Lyon")
        assert Brewery.objects.count() == 2

    def test_a_beer_of_the_homonym_is_not_compared_with_the_other_ones_beers(self, user, coin):
        f.make_beer(name="Nouvelle Blonde", brewery=coin)
        self.add(user, postal="69001")
        assert Beer.objects.filter(name="Nouvelle Blonde").count() == 2

    def test_a_fiche_without_a_location_needs_a_confirmation_to_create_a_homonym(self, user):
        f.make_brewery(name="Brasserie du Coin")  # fiche créée sans lieu
        form = self.add(user, postal="69001")
        assert not form.is_valid() and "Sa localisation n'est pas connue" in render_to_string(
            "partials/duplicate_panel.html", {"inspection": form.inspection, "confirm_brewery_name": "c", "confirm_beer_name": "b", "typed_postal_code": "69001"})
        assert Brewery.objects.count() == 1
        self.add(user, postal="69001", **{"beer-confirm_brewery": cm.find_brewery("Brasserie du Coin", "69001").token})
        assert Brewery.objects.filter(city="Lyon").exists() and Brewery.objects.count() == 2

    @pytest.mark.parametrize("postal, field", [("69", "brewery_postal_code"), ("99999", "brewery_postal_code")])
    def test_a_wrong_postal_code_is_refused(self, user, coin, postal, field):
        form = self.add(user, postal=postal)
        assert field in form.errors and not Beer.objects.exists()

    def test_the_city_must_match_the_postal_code(self, user, coin):
        assert "brewery_city" in self.add(user, postal="44000", **{"beer-brewery_city": "Paris"}).errors

    def test_a_new_brewery_gets_the_given_location(self, user):
        self.add(user, brewery="Zythos", postal="44000")
        assert Brewery.objects.get(name="Zythos").city == "Nantes"

    def test_editing_a_beer_keeps_its_own_brewery_among_homonyms(self, user, coin):
        other = f.make_brewery(name="Brasserie du Coin", postal_code="69001", city="Lyon")
        beer = f.make_beer(name="Rousse", brewery=other)
        form = BeerForm({"name": "Rousse", "brewery_name": "Brasserie du Coin", "degree": "6"}, instance=beer, user=user)
        assert form.is_valid() and form.save().brewery == other

    def test_the_brewery_chosen_in_the_list_wins_over_its_homonym(self, user, coin):
        lyon = f.make_brewery(name="Brasserie du Coin", postal_code="69001", city="Lyon")
        form = self.add(user, **{"beer-brewery_slug": lyon.slug})
        assert form.is_valid() and Beer.objects.get().brewery == lyon and Brewery.objects.count() == 2

    def test_the_chosen_brewery_is_forgotten_when_another_name_is_typed(self, user, coin):
        lyon = f.make_brewery(name="Brasserie du Coin", postal_code="69001", city="Lyon")
        self.add(user, brewery="Zythos", **{"beer-brewery_slug": lyon.slug})
        assert Beer.objects.get().brewery.name == "Zythos"

    def test_an_unknown_slug_is_ignored(self, user, coin):
        self.add(user, **{"beer-brewery_slug": "nope"})
        assert Beer.objects.get().brewery == coin

    def test_the_member_form_has_no_location_to_fill(self, user):
        form = BeerForm(prefix="beer", user=user, light=True)
        assert not {"brewery_postal_code", "brewery_city", "description"} & set(form.fields)

    def test_the_live_check_follows_the_brewery_chosen_in_the_list(self, auth_client, coin):
        lyon = f.make_brewery(name="Brasserie du Coin", postal_code="69001", city="Lyon")
        check = reverse("check_catalog")
        chosen = auth_client.get(check, {"name": "X", "brewery": "Brasserie du Coin", "slug": lyon.slug}).json()["html"]
        forgotten = auth_client.get(check, {"name": "X", "brewery": "Autre nom", "slug": lyon.slug}).json()["html"]
        assert "69001 Lyon" in chosen and "44000" not in chosen and "69001" not in forgotten

    def test_the_live_check_takes_the_location_into_account(self, auth_client, coin):
        check = reverse("check_catalog")
        same = auth_client.get(check, {"name": "X", "brewery": "Brasserie du Coin", "postal": "44000"}).json()
        other = auth_client.get(check, {"name": "X", "brewery": "Brasserie du Coin", "postal": "69001"}).json()
        assert same["apply_brewery"] == "Brasserie du Coin" and other["apply_brewery"] is None and other["html"].strip() == ""


class TestPlacesAreFoundByLocation:
    def test_search_finds_a_place_by_its_city_or_postal_code(self, auth_client):
        f.make_brewery(name="Brasserie Alpha", postal_code="44000", city="Nantes")
        f.make_bar(name="Bar Beta", postal_code="69001", city="Lyon")
        search = reverse("all_beers")
        assert [b.name for b in auth_client.get(search, {"tab": "brasseries", "q": "nantes"}).context["breweries"]] == ["Brasserie Alpha"]
        assert [b.name for b in auth_client.get(search, {"tab": "bars", "q": "69001"}).context["bars"]] == ["Bar Beta"]
