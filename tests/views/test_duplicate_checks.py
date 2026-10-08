"""Ajout d'une bière : brasseries et bières déjà au catalogue (formulaire, vérification en direct, écran d'administration)."""
from importlib import import_module
from pathlib import Path

import pytest
from django.apps import apps
from django.core.management import call_command
from django.urls import reverse

from app.forms import BeerForm
from app.models import Beer, Brewery
from app.services import catalog_matching as cm
from app.services.throttle import CATALOG_CHECK_BY_USER, Rule
from tests import factories as f
from tests.helpers import messages_of
from tests.views.test_beer_views import add_beer_data

pytestmark = pytest.mark.django_db

ADD = reverse("add_beer")
CHECK = reverse("check_catalog")


@pytest.fixture
def staff(db):
    return f.make_user(username="moderator", groups=("Staff",))


@pytest.fixture
def coin():
    return f.make_brewery(name="Brasserie du Coin")


def post(client, name="Nouvelle Blonde", brewery="Brasserie du Coin", **extra):
    return client.post(ADD, add_beer_data(name=name, brewery_name=brewery, **extra))


class TestBreweryAtSubmission:
    def test_an_identical_brewery_is_reused_not_duplicated(self, auth_client, coin):
        post(auth_client, brewery="LA BRASSERIE DU COIN SAS")
        assert Brewery.objects.filter(name__icontains="coin").count() == 1 and Beer.objects.get(name="Nouvelle Blonde").brewery_id == coin

    @pytest.mark.parametrize("typed", ["Microbrasserie du Coin", "Du Coin", "Coin Brewing"])
    def test_a_lookalike_brewery_blocks_until_chosen_or_confirmed(self, auth_client, coin, typed):
        response = post(auth_client, brewery=typed)
        assert response.status_code == 200 and Beer.objects.count() == 0 and Brewery.objects.count() == 1
        html = response.content.decode()
        assert "Une brasserie proche existe déjà" in html and "Brasserie du Coin" in html and 'name="beer-confirm_brewery"' in html
        assert 'data-use-brewery="Brasserie du Coin"' in html

    def test_the_typed_names_are_kept_so_the_member_can_correct_them(self, auth_client, coin):
        response = post(auth_client, name="Ma Bière", brewery="Microbrasserie du Coin")
        form = response.context["beer_form"]
        assert (form["name"].value(), form["brewery_name"].value()) == ("Ma Bière", "Microbrasserie du Coin")
        assert set(form.errors) == {"__all__"}

    def test_the_message_explains_what_to_do(self, auth_client, coin):
        message = " ".join(messages_of(post(auth_client, brewery="Microbrasserie du Coin")))
        assert "Une brasserie très proche existe déjà : « Brasserie du Coin »" in message and "confirmez" in message

    def test_confirming_creates_a_new_brewery(self, auth_client, coin):
        token = cm.find_brewery("Microbrasserie du Coin").token
        post(auth_client, brewery="Microbrasserie du Coin", **{"beer-confirm_brewery": token})
        assert Brewery.objects.filter(name="Microbrasserie du Coin").count() == 1 and Beer.objects.filter(name="Nouvelle Blonde").exists()

    def test_picking_the_existing_one_attaches_the_beer_to_it(self, auth_client, coin):
        post(auth_client, brewery="Brasserie du Coin")
        assert Beer.objects.get(name="Nouvelle Blonde").brewery_id == coin and Brewery.objects.count() == 1

    @pytest.mark.parametrize("token", ["", "forged", "x" * 700])
    def test_a_forged_confirmation_does_not_pass(self, auth_client, coin, token):
        post(auth_client, brewery="Microbrasserie du Coin", **{"beer-confirm_brewery": token})
        assert Beer.objects.count() == 0 and Brewery.objects.count() == 1

    def test_a_confirmation_for_another_brewery_name_does_not_pass(self, auth_client, coin):
        token = cm.find_brewery("Microbrasserie du Coin").token
        post(auth_client, brewery="Coin Brewing", **{"beer-confirm_brewery": token})
        assert Beer.objects.count() == 0


class TestBeerAtSubmission:
    @pytest.fixture
    def punk(self, coin):
        return f.make_beer(name="Punk IPA", brewery=coin)

    @pytest.mark.parametrize("typed", ["Punk IPA", "punk i.p.a.", "PUNK IPA 33cl 5,6%", "IPA Punk", "Brasserie du Coin Punk IPA"])
    def test_the_same_beer_is_refused_with_a_link_to_the_existing_one(self, auth_client, punk, typed):
        response = post(auth_client, name=typed)
        html = response.content.decode()
        assert Beer.objects.count() == 1 and "Cette bière est déjà au catalogue" in html and reverse("beer_detail", args=[punk.slug]) in html

    def test_it_cannot_be_forced_by_a_token(self, auth_client, punk):
        post(auth_client, name="Punk IPA", **{"beer-confirm_beer": "anything"})
        assert Beer.objects.count() == 1

    def test_the_same_beer_through_a_lookalike_brewery_is_refused_too(self, auth_client, punk):
        token = cm.find_brewery("Microbrasserie du Coin").token  # l'utilisateur n'a confirmé que la brasserie
        post(auth_client, name="Punk IPA", brewery="Microbrasserie du Coin")
        assert Beer.objects.count() == 1 and token

    def test_a_close_name_asks_for_a_choice_and_can_be_confirmed(self, auth_client, punk):
        response = post(auth_client, name="Punk IPAA")
        assert "Une bière très proche existe déjà" in response.content.decode() and Beer.objects.count() == 1
        token = cm.inspect("Punk IPAA", "Brasserie du Coin").beer.token
        post(auth_client, name="Punk IPAA", **{"beer-confirm_beer": token})
        assert Beer.objects.filter(name="Punk IPAA").exists()

    def test_the_same_name_at_another_brewery_is_allowed_with_a_notice(self, auth_client, punk):
        response = post(auth_client, name="Punk IPA", brewery="Brasserie du Port", **{"drink-note": "11"})  # une erreur ailleurs pour réafficher la page
        assert "Une bière du même nom existe chez" in response.content.decode()
        post(auth_client, name="Punk IPA", brewery="Brasserie du Port")
        assert Beer.objects.filter(name="Punk IPA").count() == 2

    def test_distinct_beers_of_the_same_brewery_are_accepted(self, auth_client, punk):
        f.make_beer(name="Houblon 1", brewery=punk.brewery_id)
        post(auth_client, name="Houblon 2")
        assert Beer.objects.filter(name="Houblon 2").exists()


class TestEditing:
    def test_a_beer_can_be_saved_without_colliding_with_itself(self, auth_client, user, coin):
        beer = f.make_beer(name="Punk IPA", brewery=coin, added_by=user)
        response = auth_client.post(reverse("edit_beer", args=[beer.slug]), {"name": "Punk IPA", "brewery_name": "Brasserie du Coin", "degree": "6.0"})
        assert response.status_code == 302

    def test_renaming_into_an_existing_beer_is_refused_and_explained_on_the_page(self, auth_client, user, coin):
        f.make_beer(name="Punk IPA", brewery=coin)
        mine = f.make_beer(name="Houblon", brewery=coin, added_by=user)
        response = auth_client.post(reverse("edit_beer", args=[mine.slug]), {"name": "Punk I.P.A.", "brewery_name": "Brasserie du Coin", "degree": "6.0"})
        assert response.status_code == 200 and "Cette bière est déjà au catalogue" in response.content.decode()
        assert Beer.objects.get(pk=mine.pk).name == "Houblon"


class TestLiveCheckApi:
    def get(self, client, **params):
        return client.get(CHECK, params)

    def test_a_lookalike_brewery_gives_the_panel_with_its_token(self, auth_client, coin):
        body = self.get(auth_client, name="Nouvelle Blonde", brewery="Microbrasserie du Coin").json()
        assert 'data-duplicate="brewery-probable"' in body["html"] and 'name="beer-confirm_brewery"' in body["html"] and body["apply_brewery"] is None

    def test_an_identical_brewery_is_proposed_under_its_exact_name(self, auth_client, coin):
        body = self.get(auth_client, name="Nouvelle Blonde", brewery="la brasserie du coin").json()
        assert body["apply_brewery"] == "Brasserie du Coin" and 'data-duplicate="brewery-same"' in body["html"]

    def test_an_existing_beer_is_reported(self, auth_client, coin):
        beer = f.make_beer(name="Punk IPA", brewery=coin)
        html = self.get(auth_client, name="punk i.p.a.", brewery="Brasserie du Coin").json()["html"]
        assert 'data-duplicate="beer-same"' in html and reverse("beer_detail", args=[beer.slug]) in html

    def test_nothing_to_say_gives_an_empty_panel(self, auth_client, coin):
        body = self.get(auth_client, name="Nouvelle Blonde", brewery="Zythos").json()
        assert body["html"].strip() == "" and body["apply_brewery"] is None

    @pytest.mark.parametrize("params", [{}, {"name": "a"}, {"name": " ", "brewery": " "}])
    def test_too_little_input_does_nothing(self, auth_client, coin, params):
        assert self.get(auth_client, **params).json() == {"html": "", "apply_brewery": None}

    def test_the_token_given_by_the_api_is_accepted_by_the_form(self, auth_client, coin):
        html = self.get(auth_client, name="Nouvelle Blonde", brewery="Microbrasserie du Coin").json()["html"]
        token = html.split('name="beer-confirm_brewery" value="')[1].split('"')[0]
        post(auth_client, brewery="Microbrasserie du Coin", **{"beer-confirm_brewery": token})
        assert Beer.objects.filter(name="Nouvelle Blonde").exists()

    @pytest.mark.parametrize("payload", ["<script>alert(1)</script>", '"><img src=x onerror=alert(1)>', "' OR 1=1 --", "%", "a" * 5000])
    def test_hostile_input_is_harmless(self, auth_client, coin, payload):
        response = self.get(auth_client, name=payload, brewery=payload)
        assert response.status_code == 200 and payload not in response.json()["html"] and Brewery.objects.count() == 1

    def test_input_is_bounded(self, auth_client, coin):
        assert self.get(auth_client, name="mot " * 5000, brewery="x" * 9000).status_code == 200

    def test_html_in_existing_names_is_escaped(self, auth_client):
        f.make_brewery(name="Brasserie du Coin")
        Brewery.objects.filter(name="Brasserie du Coin").update(name='Brasserie <b>"du"</b> Coin')
        html = self.get(auth_client, name="Nouvelle", brewery='Brasserie <b>"du"</b> Coin').json()["html"]
        assert "<b>" not in html

    def test_it_is_throttled_per_member(self, auth_client, other_client, coin, monkeypatch):
        monkeypatch.setattr("app.views.api_views.CATALOG_CHECK_BY_USER", Rule("catalog-check", 2, CATALOG_CHECK_BY_USER.window))
        codes = [self.get(auth_client, name="Punk", brewery="Zythos").status_code for _ in range(3)]
        assert codes == [200, 200, 429] and self.get(other_client, name="Punk", brewery="Zythos").status_code == 200

    def test_login_and_get_are_required(self, client, auth_client):
        assert client.get(CHECK, {"name": "x"}).status_code == 302
        assert auth_client.post(CHECK).status_code == 405


class TestPagesCarryThePanel:
    def test_the_add_page_has_the_live_panel_and_script(self, auth_client):
        html = auth_client.get(ADD).content.decode()
        assert 'id="duplicate-panel"' in html and f'data-url="{CHECK}"' in html and "script/catalog_check.js" in html

    def test_the_edit_page_shows_the_panel_after_a_refusal(self, auth_client, user, coin):
        f.make_beer(name="Punk IPA", brewery=coin)
        mine = f.make_beer(name="Houblon", brewery=coin, added_by=user)
        html = auth_client.post(reverse("edit_beer", args=[mine.slug]), {"name": "Punk IPA", "brewery_name": "Brasserie du Coin", "degree": "6"}).content.decode()
        assert 'data-duplicate="beer-same"' in html


class TestCatalogueUnderTheNewRules:
    def test_every_stored_name_has_its_keys(self, coin):
        beer = f.make_beer(name="Punk I.P.A. 33cl", brewery=coin)
        assert (coin.name_key, coin.match_key) == ("brasserie coin", "coin") and (beer.name_key, beer.match_key) == ("ipa punk", "ipa punk")

    def test_keys_follow_a_rename(self, coin):
        coin.name = "Microbrasserie des Alpes"
        coin.save()
        assert Brewery.objects.get(pk=coin.pk).match_key == "alpes"

    def test_saving_only_the_name_still_refreshes_the_keys(self, coin):
        Brewery.objects.filter(pk=coin.pk).update(name_key="", match_key="")
        coin.refresh_from_db()
        coin.name = "Brasserie Neuve"
        coin.save(update_fields=["name"])
        assert Brewery.objects.get(pk=coin.pk).match_key == "neuve"

    def test_keys_are_not_editable_through_forms(self):
        assert BeerForm.Meta.model._meta.get_field("name_key").editable is False

    def test_the_backfill_fills_the_keys_of_existing_rows(self, coin):
        beer = f.make_beer(name="Punk IPA", brewery=coin)
        Brewery.objects.update(name_key="", match_key="")
        Beer.objects.update(name_key="", match_key="")
        import_module("app.migrations.0072_catalog_match_keys").fill_match_keys(apps, None)
        assert Brewery.objects.get(pk=coin.pk).match_key == "coin" and Beer.objects.get(pk=beer.pk).name_key == "ipa punk"

    def test_the_trigram_indexes_exist(self):
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename IN ('app_beer', 'app_brewery')")
            names = {row[0] for row in cursor.fetchall()}
        assert {"beer_match_key_trgm", "brewery_match_key_trgm"} <= names


class TestAdministration:
    def test_staff_sees_the_probable_duplicates(self, client_for, staff, coin):
        f.make_brewery(name="Microbrasserie du Coin")
        response = client_for(staff).get(reverse("admin_duplicates"))
        html = response.content.decode()
        assert response.status_code == 200 and "Microbrasserie du Coin" in html and "Brasserie du Coin" in html and "Proches" in html

    def test_members_cannot_see_it(self, auth_client, client):
        assert auth_client.get(reverse("admin_duplicates")).status_code in (302, 403) and client.get(reverse("admin_duplicates")).status_code == 302

    def test_read_only(self, client_for, staff):
        assert client_for(staff).post(reverse("admin_duplicates")).status_code == 405

    def test_the_command_lists_pairs_and_can_rebuild_keys(self, coin, capsys):
        f.make_brewery(name="Microbrasserie du Coin")
        Brewery.objects.update(name_key="", match_key="")
        call_command("find_duplicates", "--rebuild-keys")
        out = capsys.readouterr().out
        assert "Clés recalculées" in out and "Brasserie du Coin  <->  Microbrasserie du Coin" in out or "Microbrasserie du Coin  <->  Brasserie du Coin" in out


class TestClientScript:
    SOURCE = Path("app/static/script/catalog_check.js").read_text()

    def test_it_only_reads_from_the_same_origin_and_stores_nothing(self):
        assert self.SOURCE.count("fetch(") == 1 and "credentials: 'same-origin'" in self.SOURCE and "method" not in self.SOURCE
        assert "localStorage" not in self.SOURCE and "eval(" not in self.SOURCE and "document.write" not in self.SOURCE

    def test_it_is_debounced_and_cancels_stale_requests(self):
        assert "DEBOUNCE_MS" in self.SOURCE and "AbortController" in self.SOURCE and "controller.abort()" in self.SOURCE

    def test_the_only_html_inserted_comes_from_the_server_panel(self):
        assert self.SOURCE.count("innerHTML") == 1 and "panel.innerHTML = data.html" in self.SOURCE
