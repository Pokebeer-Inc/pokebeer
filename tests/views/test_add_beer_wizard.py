"""Ajout d'une bière par étapes : seul le nom est indispensable, brouillon enregistré à chaque étape, page de félicitations."""

import pytest
from django.urls import reverse

from app.models import Beer, BeerDraft, Drinks, ThrottleHit
from tests import factories as f
from tests.helpers import assert_redirects, messages_of

pytestmark = pytest.mark.django_db

DRAFT = "save_beer_draft"


def post_step(client, step, strict=True, **fields):
    data = {"step": step, "strict": "1" if strict else "0", **fields}
    return client.post(reverse(DRAFT), data)


def full_data(**overrides):
    return {"beer-name": "Nouvelle Blonde", "beer-brewery_name": "Brasserie Test", "beer-degree": "6.5", "beer-style": "blonde", **overrides}


class TestWizardPage:
    def test_the_page_is_made_of_two_steps_in_one_form(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        assert html.count('class="wizard-step"') == 2 and html.count("<form") >= 1
        for number in range(1, 3):
            assert f'data-step="{number}"' in html
        assert 'id="wizard-next"' in html and 'id="wizard-back"' in html and "add_beer_wizard.js" in html
        assert 'id="duplicate-panel"' in html and 'id="scan-label-btn"' in html  # scanner et contrôle des doublons conservés

    def test_a_member_has_no_review_step_and_submits_from_the_last_one(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        assert "wizard-recap" not in html and "Non renseigné" not in html and "Vérification" not in html
        assert html.count('id="wizard-submit"') == 1 and html.index('data-step="2"') < html.index('id="wizard-submit"')

    def test_a_member_is_not_asked_for_what_only_managers_know(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        for name in ("beer-name", "beer-brewery_name", "beer-degree", "beer-style", "beer-bitterness", "beer-image", "beer-ean"):
            assert f'name="{name}"' in html
        for name in ("beer-brewery_postal_code", "beer-brewery_city", "beer-description", "drink-comment", "drink-note"):
            assert f'name="{name}"' not in html

    def test_only_the_name_and_the_degree_are_required(self, auth_client):
        beer_form = auth_client.get(reverse("add_beer")).context["beer_form"]
        assert {name for name, field in beer_form.fields.items() if field.required} == {"name", "degree"}

class TestStepValidation:
    def test_step_1_needs_a_name_and_a_degree_but_no_brewery(self, auth_client):
        response = post_step(auth_client, 1)
        assert response.status_code == 400
        errors = " ".join(response.json()["errors"])
        assert "Nom de la bière" in errors and "Alcool" in errors and "Brasserie" not in errors
        assert not BeerDraft.objects.exists()  # une étape refusée ne laisse rien

    def test_a_valid_step_is_saved_and_moves_the_draft_forward(self, auth_client, user):
        response = post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-degree": "5"})
        assert response.status_code == 200 and response.json() == {"ok": True}
        draft = BeerDraft.objects.get(user=user)
        assert draft.data["beer-name"] == "Ma Blonde" and draft.data["beer-degree"] == "5" and draft.current_step == 2

    def test_step_1_rejects_an_impossible_degree(self, auth_client):
        assert post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-degree": "101"}).status_code == 400

    def test_the_details_step_accepts_nothing(self, auth_client):
        post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-degree": "5"})
        assert post_step(auth_client, 2).status_code == 200  # style, IBU et photo : facultatifs

    def test_the_details_step_validates_what_is_given(self, auth_client):
        post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-degree": "5"})
        assert post_step(auth_client, 2, **{"beer-bitterness": "9999"}).status_code == 400

    def test_duplicates_are_still_caught_at_the_first_step(self, auth_client, beer):
        response = post_step(auth_client, 1, **{"beer-name": "test ipa", "beer-brewery_name": "Brasserie Test", "beer-degree": "5"})
        assert response.status_code == 400 and "existe déjà" in " ".join(response.json()["errors"])
        assert not BeerDraft.objects.exists()

    def test_errors_of_other_steps_do_not_block_this_one(self, auth_client):
        # la bière est valide alors que l'amertume (étape 2) est absurde
        assert post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-degree": "5", "beer-bitterness": "9999"}).status_code == 200

    def test_unknown_or_missing_steps_are_refused(self, auth_client):
        for step in ("0", "3", "abc", ""):
            assert post_step(auth_client, step).status_code == 400


class TestDraftStorage:
    def test_a_soft_save_keeps_whatever_was_typed_without_validating(self, auth_client, user):
        response = post_step(auth_client, 2, strict=False, **{"beer-name": "A", "beer-degree": "n'importe quoi"})
        assert response.status_code == 204
        draft = BeerDraft.objects.get(user=user)
        assert draft.data["beer-name"] == "A" and draft.current_step == 2

    def test_only_whitelisted_text_fields_are_stored_and_truncated(self, auth_client, user):
        post_step(auth_client, 1, strict=False, **{"beer-name": "N" * 500, "is_staff": "1", "beer-image": "x", "beer-confirm_beer": "tok", "drink-comment": "c" * 5000, "beer-ean": "123"})
        data = BeerDraft.objects.get(user=user).data
        assert len(data["beer-name"]) == 150
        assert set(data) <= {"beer-name", "beer-ean"} and "is_staff" not in data and "beer-confirm_beer" not in data and "drink-comment" not in data

    def test_one_draft_per_member_and_data_is_merged(self, auth_client, user):
        post_step(auth_client, 1, strict=False, **{"beer-name": "A"})
        post_step(auth_client, 2, strict=False, **{"beer-degree": "5"})
        assert BeerDraft.objects.filter(user=user).count() == 1
        assert BeerDraft.objects.get(user=user).data == {"beer-name": "A", "beer-degree": "5"}

    def test_a_draft_belongs_to_one_member_only(self, auth_client, other_client, user, other_user):
        post_step(auth_client, 1, strict=False, **{"beer-name": "Secrète"})
        page = other_client.get(reverse("add_beer"))
        assert "Secrète" not in page.content.decode() and not BeerDraft.objects.filter(user=other_user).exists()

    def test_stale_drafts_are_purged_when_a_new_one_is_saved(self, auth_client, other_user):
        from datetime import timedelta
        from django.utils import timezone
        old = BeerDraft.objects.create(user=other_user, data={"beer-name": "Vieux"})
        BeerDraft.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=40))
        post_step(auth_client, 1, strict=False, **{"beer-name": "Neuf"})
        assert not BeerDraft.objects.filter(pk=old.pk).exists()

    def test_the_draft_goes_with_the_account(self, user):
        BeerDraft.objects.create(user=user, data={})
        user.delete()
        assert not BeerDraft.objects.exists()

    def test_oversized_bodies_and_floods_are_refused(self, auth_client):
        assert post_step(auth_client, 1, strict=False, **{"beer-description": "d" * 30000}).status_code == 413
        for _ in range(200):
            ThrottleHit.objects.create(scope="beer-draft", key_hash=__import__("app.services.protection.throttle", fromlist=["_digest"])._digest(auth_client.session["_auth_user_id"]))
        assert post_step(auth_client, 1, strict=False, **{"beer-name": "x"}).status_code == 429

    def test_post_only_and_login_required(self, auth_client, client):
        assert auth_client.get(reverse(DRAFT)).status_code == 405
        assert client.post(reverse(DRAFT), {"step": 1}).status_code == 302


class TestResume:
    def test_the_page_resumes_at_the_saved_step_with_the_saved_values(self, auth_client):
        post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-brewery_name": "Brasserie X", "beer-degree": "5.5"})
        response = auth_client.get(reverse("add_beer"))
        html = response.content.decode()
        assert response.context["start_step"] == 2 and response.context["resumed"] is True
        assert 'data-start-step="2"' in html and "Ma Blonde" in html and 'value="5.5"' in html
        assert "repris là où vous l'aviez laissé" in html and reverse("discard_beer_draft") in html

    def test_no_draft_means_a_fresh_form_at_step_one(self, auth_client):
        response = auth_client.get(reverse("add_beer"))
        assert response.context["start_step"] == 1 and not response.context["resumed"]

    def test_a_brewery_link_starts_from_scratch_and_keeps_the_draft(self, auth_client, user):
        post_step(auth_client, 1, strict=False, **{"beer-name": "En cours"})
        response = auth_client.get(reverse("add_beer"), {"brewery": "Mont Blanc"})
        assert response.context["beer_form"].initial["brewery_name"] == "Mont Blanc" and not response.context["resumed"]
        assert BeerDraft.objects.filter(user=user).exists()

    def test_discarding_starts_over(self, auth_client, user):
        post_step(auth_client, 1, strict=False, **{"beer-name": "A jeter"})
        response = auth_client.post(reverse("discard_beer_draft"))
        assert response.status_code == 302 and response.url == reverse("add_beer")
        assert not BeerDraft.objects.filter(user=user).exists()
        assert auth_client.get(reverse("discard_beer_draft")).status_code == 405


class TestFinishing:
    def test_the_final_submit_creates_the_beer_without_a_tasting_and_removes_the_draft(self, auth_client, user):
        post_step(auth_client, 1, strict=False, **{"beer-name": "Nouvelle Blonde"})
        response = auth_client.post(reverse("add_beer"), full_data())
        beer = Beer.objects.get(name="Nouvelle Blonde")
        assert response.status_code == 302 and response.url == reverse("add_beer_done", args=[beer.slug])
        assert beer.added_by == user and beer.brewery.name == "Brasserie Test"
        assert not Drinks.objects.filter(beer=beer).exists()  # ajouter n'est pas déguster
        assert not BeerDraft.objects.filter(user=user).exists()

    def test_a_beer_can_be_added_with_nothing_but_a_name_and_a_degree(self, auth_client):
        response = auth_client.post(reverse("add_beer"), {"beer-name": "Pinte du comptoir", "beer-degree": "5"})
        beer = Beer.objects.get(name="Pinte du comptoir")
        assert response.status_code == 302 and beer.brewery is None and beer.brewery_label == "Brasserie inconnue" and beer.needs_review

    def test_a_refused_submit_reopens_the_step_to_fix_and_keeps_the_draft(self, auth_client, user):
        post_step(auth_client, 1, strict=False, **{"beer-name": "Brouillon"})
        response = auth_client.post(reverse("add_beer"), full_data(**{"beer-degree": "101"}))
        assert response.status_code == 200 and response.context["start_step"] == 1
        assert BeerDraft.objects.filter(user=user).exists() and not Beer.objects.filter(name="Nouvelle Blonde").exists()

    @pytest.mark.parametrize("overrides, step", [({"beer-name": ""}, 1), ({"beer-degree": ""}, 1), ({"beer-bitterness": "9999"}, 2)])
    def test_each_error_reopens_its_own_step(self, auth_client, overrides, step):
        response = auth_client.post(reverse("add_beer"), full_data(**overrides))
        assert response.context["start_step"] == step

    def test_a_duplicate_reopens_the_first_step(self, auth_client, beer):
        response = auth_client.post(reverse("add_beer"), full_data(**{"beer-name": "test ipa", "beer-brewery_name": "Brasserie Test"}))
        assert response.context["start_step"] == 1


class TestCelebrationPage:
    def test_the_author_sees_the_celebration_with_the_beer(self, auth_client, user):
        beer = f.make_beer(name="Ma Création", added_by=user)
        response = auth_client.get(reverse("add_beer_done", args=[beer.slug]))
        html = response.content.decode()
        assert response.status_code == 200 and "Ma Création" in html and reverse("beer_detail", args=[beer.slug]) in html
        assert reverse("add_beer") in html and "confetti" in html

    def test_nobody_else_can_open_it(self, auth_client, other_user):
        beer = f.make_beer(added_by=other_user)
        assert auth_client.get(reverse("add_beer_done", args=[beer.slug])).status_code == 404

    def test_removed_beers_and_anonymous_visitors_are_refused(self, auth_client, client, user):
        removed = f.make_beer(added_by=user, is_deleted=True)
        assert auth_client.get(reverse("add_beer_done", args=[removed.slug])).status_code == 404
        assert client.get(reverse("add_beer_done", args=["x"])).status_code == 302


class TestQuickRatingOnTheCelebrationPage:
    """Ajouter n'est pas déguster : la note se donne ensuite, en un geste, sur la page de félicitations."""

    @pytest.fixture
    def added(self, user):
        return f.make_beer(name="Ma Création", added_by=user)

    def quick(self, client, beer, **data):
        return client.post(reverse("quick_rate_beer", args=[beer.slug]), data, HTTP_REFERER=reverse("add_beer_done", args=[beer.slug]))

    def test_the_page_offers_the_rating_with_every_note(self, auth_client, added):
        html = auth_client.get(reverse("add_beer_done", args=[added.slug])).content.decode()
        assert reverse("quick_rate_beer", args=[added.slug]) in html and "quick_rating.js" in html
        assert all(f'name="note" value="{value}"' in html for value in range(11))
        assert 'name="comment"' in html and "Plus tard" in html and "<details" not in html.split('id="quick-rating"')[1].split("</form>")[0]
        assert "disabled" not in html.split('id="quick-rating-submit"')[1].split(">")[0]

    def test_the_card_has_two_steps_the_second_one_asks_for_the_context(self, auth_client, added):
        html = auth_client.get(reverse("add_beer_done", args=[added.slug])).content.decode()
        card = html.split('id="quick-rating"')[1].split("</form>")[0]
        assert "data-stepper" in html and 'data-stepper-step="1"' in card and 'data-stepper-step="2"' in card and "data-stepper-step=\"3\"" not in card
        step_two = card.split('data-stepper-step="2"')[1]
        for name in ("venue_type", "company", "serving_format", "price"):
            assert f'name="{name}"' in step_two
        assert 'name="note"' not in step_two and "data-stepper-next" in card and "data-stepper-submit" in card

    def test_the_context_is_saved_with_the_note(self, auth_client, user, added):
        self.quick(auth_client, added, note="8", venue_type="bar", company="friends", serving_format="pint", price="6.50")
        drink = Drinks.objects.get(drinker=user, beer=added)
        assert (drink.note, drink.venue_type, drink.company, drink.serving_format, str(drink.price)) == (8, "bar", "friends", "pint", "6.50")

    def test_skipping_the_context_is_fine(self, auth_client, user, added):
        self.quick(auth_client, added, note="8", venue_type="", company="", serving_format="", price="")
        drink = Drinks.objects.get(drinker=user, beer=added)
        assert (drink.venue_type, drink.company, drink.serving_format, drink.price) == ("", "", "", None)

    def test_a_bad_context_choice_is_refused(self, auth_client, added):
        self.quick(auth_client, added, note="8", venue_type="moon")
        assert not Drinks.objects.exists()

    def test_a_note_alone_is_saved_and_leads_to_the_second_celebration(self, auth_client, user, added):
        response = self.quick(auth_client, added, note="8")
        assert_redirects(response, reverse("rate_beer_done", args=[added.slug]))
        drink = Drinks.objects.get(drinker=user, beer=added)
        assert (drink.note, drink.comment) == (8, "")
        done = auth_client.get(reverse("rate_beer_done", args=[added.slug])).content.decode()
        assert "8/10" in done and f'href="{reverse("beer_detail", args=[added.slug])}"' in done  # « Continuer » mène à la bière, pas au formulaire

    def test_a_comment_alone_is_saved(self, auth_client, user, added):
        self.quick(auth_client, added, comment="Très fruitée")
        drink = Drinks.objects.get(drinker=user, beer=added)
        assert (drink.note, drink.comment) == (None, "Très fruitée")

    def test_an_empty_reaction_creates_nothing_and_goes_back_with_the_reason(self, auth_client, added):
        response = self.quick(auth_client, added)
        assert_redirects(response, reverse("add_beer_done", args=[added.slug]))
        assert not Drinks.objects.exists()
        assert "Donnez une note ou écrivez quelques mots." in " ".join(messages_of(response))

    def test_once_rated_the_page_no_longer_offers_it(self, auth_client, added):
        self.quick(auth_client, added, note="6")
        html = auth_client.get(reverse("add_beer_done", args=[added.slug])).content.decode()
        assert reverse("quick_rate_beer", args=[added.slug]) not in html and "quick_rating.js" not in html
        self.quick(auth_client, added, note="1")  # un second envoi ne change rien
        assert list(Drinks.objects.values_list("note", flat=True)) == [6]

    def test_the_quick_rating_follows_the_same_rules_as_any_rating(self, auth_client, user, added):
        user.wishlist_beers.add(added)
        self.quick(auth_client, added, note="11")
        assert not Drinks.objects.exists()
        self.quick(auth_client, added, note="9")
        assert not user.wishlist_beers.exists() and Drinks.objects.filter(beer=added).count() == 1

    def test_a_removed_beer_cannot_be_rated_and_login_is_required(self, auth_client, client, user):
        removed = f.make_beer(added_by=user, is_deleted=True)
        assert self.quick(auth_client, removed, note="5").status_code == 404
        assert client.post(reverse("quick_rate_beer", args=[removed.slug]), {"note": "5"}).status_code == 302

    def test_the_celebration_tells_when_the_brewery_is_unknown(self, auth_client, user):
        beer = f.make_beer(name="Pinte", unbranded=True, added_by=user)
        html = auth_client.get(reverse("add_beer_done", args=[beer.slug])).content.decode()
        assert "retrouvera sa brasserie" in html


class TestWithRealCsrfChecks:
    """Le navigateur envoie un jeton CSRF que le middleware lit avant la vue : le corps de la requête n'est alors plus relisible."""

    def test_saving_a_step_works_when_csrf_protection_reads_the_form_first(self, user):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        client.get(reverse("add_beer"))
        token = client.cookies["csrftoken"].value
        response = client.post(reverse(DRAFT), {"csrfmiddlewaretoken": token, "step": "1", "strict": "1", "beer-name": "Etoile", "beer-brewery_name": "Brasserie Z", "beer-degree": "5"})
        assert response.status_code == 200 and response.json() == {"ok": True}
        soft = client.post(reverse(DRAFT), {"csrfmiddlewaretoken": token, "step": "2", "strict": "0", "beer-degree": "5"})
        assert soft.status_code == 204
        refused = client.post(reverse(DRAFT), {"step": "1", "strict": "0"})
        assert refused.status_code == 403
