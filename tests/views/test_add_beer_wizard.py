"""Ajout d'une bière par étapes : brouillon enregistré à chaque étape, mêmes règles qu'avant, page de félicitations."""

import pytest
from django.urls import reverse

from app.models import Beer, BeerDraft, Drinks, ThrottleHit
from tests import factories as f

pytestmark = pytest.mark.django_db

DRAFT = "save_beer_draft"


def post_step(client, step, strict=True, **fields):
    data = {"step": step, "strict": "1" if strict else "0", **fields}
    return client.post(reverse(DRAFT), data)


def full_data(**overrides):
    return {"beer-name": "Nouvelle Blonde", "beer-brewery_name": "Brasserie Test", "beer-degree": "6.5", "beer-style": "blonde",
            "drink-date": "2026-01-15", "drink-note": "8", "drink-comment": "Fruitée", **overrides}


class TestWizardPage:
    def test_the_page_is_made_of_six_steps_in_one_form(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        assert html.count('class="wizard-step"') == 6 and html.count("<form") >= 1
        for number in range(1, 7):
            assert f'data-step="{number}"' in html
        assert 'id="wizard-next"' in html and 'id="wizard-back"' in html and "add_beer_wizard.js" in html
        assert 'id="duplicate-panel"' in html and 'id="scan-label-btn"' in html  # scanner et contrôle des doublons conservés

    def test_every_field_is_still_present_with_its_original_name(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        for name in ("beer-name", "beer-brewery_name", "beer-brewery_postal_code", "beer-brewery_city", "beer-degree", "beer-style", "beer-bitterness",
                     "beer-description", "beer-image", "beer-ean", "drink-note", "drink-date", "drink-comment", "drink-photo",
                     "drink-venue_type", "drink-company", "drink-serving_format", "drink-price"):
            assert f'name="{name}"' in html

    def test_required_fields_are_unchanged(self, auth_client):
        response = auth_client.get(reverse("add_beer"))
        beer_form, drink_form = response.context["beer_form"], response.context["drink_form"]
        required = {name for name, field in beer_form.fields.items() if field.required} | {f"drink:{name}" for name, field in drink_form.fields.items() if field.required}
        assert required == {"name", "brewery_name", "degree", "drink:date", "drink:comment"}

class TestStepValidation:
    def test_step_1_needs_a_name_and_a_brewery(self, auth_client):
        response = post_step(auth_client, 1)
        assert response.status_code == 400
        errors = " ".join(response.json()["errors"])
        assert "Nom de la bière" in errors and "Brasserie" in errors
        assert not BeerDraft.objects.exists()  # une étape refusée ne laisse rien

    def test_a_valid_step_is_saved_and_moves_the_draft_forward(self, auth_client, user):
        response = post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-brewery_name": "Brasserie X"})
        assert response.status_code == 200 and response.json() == {"ok": True}
        draft = BeerDraft.objects.get(user=user)
        assert draft.data["beer-name"] == "Ma Blonde" and draft.data["beer-brewery_name"] == "Brasserie X" and draft.current_step == 2

    def test_step_2_requires_the_alcohol_degree_like_before(self, auth_client):
        post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-brewery_name": "Brasserie X"})
        refused = post_step(auth_client, 2, **{"beer-style": "ipa"})
        assert refused.status_code == 400 and "Alcool" in " ".join(refused.json()["errors"])
        assert post_step(auth_client, 2, **{"beer-degree": "5.5", "beer-style": "ipa"}).status_code == 200

    def test_step_2_rejects_an_impossible_degree(self, auth_client):
        post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-brewery_name": "Brasserie X"})
        assert post_step(auth_client, 2, **{"beer-degree": "101"}).status_code == 400

    def test_optional_steps_accept_nothing(self, auth_client):
        post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-brewery_name": "Brasserie X"})
        assert post_step(auth_client, 3).status_code == 200  # description et photo : facultatives
        assert post_step(auth_client, 5).status_code == 200  # contexte : facultatif

    def test_step_4_requires_a_comment_and_a_date(self, auth_client):
        post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-brewery_name": "Brasserie X"})
        refused = post_step(auth_client, 4, **{"drink-date": ""})
        errors = " ".join(refused.json()["errors"])
        assert refused.status_code == 400 and "Mon avis personnel" in errors and "Date de dégustation" in errors
        assert post_step(auth_client, 4, **{"drink-date": "2026-01-15", "drink-comment": "Très bien", "drink-note": "8"}).status_code == 200

    def test_step_4_refuses_a_note_above_ten(self, auth_client):
        assert post_step(auth_client, 4, **{"drink-date": "2026-01-15", "drink-comment": "x", "drink-note": "11"}).status_code == 400

    def test_a_future_date_is_refused(self, auth_client):
        assert post_step(auth_client, 4, **{"drink-date": "2099-01-01", "drink-comment": "x"}).status_code == 400

    def test_the_context_choices_are_validated(self, auth_client):
        assert post_step(auth_client, 5, **{"drink-venue_type": "moon"}).status_code == 400
        assert post_step(auth_client, 5, **{"drink-price": "-3"}).status_code == 400
        assert post_step(auth_client, 5, **{"drink-venue_type": "bar", "drink-company": "friends", "drink-serving_format": "pint", "drink-price": "6.50"}).status_code == 200

    def test_duplicates_are_still_caught_at_the_first_step(self, auth_client, beer):
        response = post_step(auth_client, 1, **{"beer-name": "test ipa", "beer-brewery_name": "Brasserie Test"})
        assert response.status_code == 400 and "existe déjà" in " ".join(response.json()["errors"])
        assert not BeerDraft.objects.exists()

    def test_errors_of_other_steps_do_not_block_this_one(self, auth_client):
        # le nom et la brasserie sont valides alors que l'alcool (étape 2) manque encore
        assert post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-brewery_name": "Brasserie X"}).status_code == 200

    def test_unknown_or_missing_steps_are_refused(self, auth_client):
        for step in ("0", "7", "abc", ""):
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
        assert len(data["beer-name"]) == 150 and len(data["drink-comment"]) == 2000
        assert set(data) <= {"beer-name", "drink-comment", "beer-ean"} and "is_staff" not in data and "beer-confirm_beer" not in data

    def test_one_draft_per_member_and_data_is_merged(self, auth_client, user):
        post_step(auth_client, 1, strict=False, **{"beer-name": "A"})
        post_step(auth_client, 2, strict=False, **{"beer-degree": "5"})
        assert BeerDraft.objects.filter(user=user).count() == 1
        assert BeerDraft.objects.get(user=user).data == {"beer-name": "A", "beer-degree": "5"}

    def test_notebooks_are_kept_when_sent(self, auth_client, user):
        post_step(auth_client, 5, strict=False, notebooks_present="1", notebooks=["mon-carnet", "autre"])
        assert BeerDraft.objects.get(user=user).data["notebooks"] == ["mon-carnet", "autre"]

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
        post_step(auth_client, 1, **{"beer-name": "Ma Blonde", "beer-brewery_name": "Brasserie X"})
        post_step(auth_client, 2, **{"beer-degree": "5.5", "beer-style": "ipa"})
        response = auth_client.get(reverse("add_beer"))
        html = response.content.decode()
        assert response.context["start_step"] == 3 and response.context["resumed"] is True
        assert 'data-start-step="3"' in html and "Ma Blonde" in html and 'value="5.5"' in html
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
    def test_the_final_submit_creates_the_beer_the_tasting_and_removes_the_draft(self, auth_client, user):
        post_step(auth_client, 1, strict=False, **{"beer-name": "Nouvelle Blonde"})
        response = auth_client.post(reverse("add_beer"), full_data(**{"drink-venue_type": "bar", "drink-company": "friends", "drink-serving_format": "pint", "drink-price": "6.50"}))
        beer = Beer.objects.get(name="Nouvelle Blonde")
        assert response.status_code == 302 and response.url == reverse("add_beer_done", args=[beer.slug])
        drink = Drinks.objects.get(beer=beer)
        assert (drink.venue_type, drink.company, drink.serving_format, str(drink.price)) == ("bar", "friends", "pint", "6.50")
        assert not BeerDraft.objects.filter(user=user).exists()

    def test_a_refused_submit_reopens_the_step_to_fix_and_keeps_the_draft(self, auth_client, user):
        post_step(auth_client, 1, strict=False, **{"beer-name": "Brouillon"})
        response = auth_client.post(reverse("add_beer"), full_data(**{"beer-degree": "101"}))
        assert response.status_code == 200 and response.context["start_step"] == 2
        assert BeerDraft.objects.filter(user=user).exists() and not Beer.objects.filter(name="Nouvelle Blonde").exists()

    @pytest.mark.parametrize("overrides, step", [({"beer-name": ""}, 1), ({"beer-degree": ""}, 2), ({"drink-comment": ""}, 4), ({"drink-price": "-1"}, 5), ({"drink-note": "11"}, 4)])
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


class TestWithRealCsrfChecks:
    """Le navigateur envoie un jeton CSRF que le middleware lit avant la vue : le corps de la requête n'est alors plus relisible."""

    def test_saving_a_step_works_when_csrf_protection_reads_the_form_first(self, user):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        client.get(reverse("add_beer"))
        token = client.cookies["csrftoken"].value
        response = client.post(reverse(DRAFT), {"csrfmiddlewaretoken": token, "step": "1", "strict": "1", "beer-name": "Etoile", "beer-brewery_name": "Brasserie Z"})
        assert response.status_code == 200 and response.json() == {"ok": True}
        soft = client.post(reverse(DRAFT), {"csrfmiddlewaretoken": token, "step": "2", "strict": "0", "beer-degree": "5"})
        assert soft.status_code == 204
        refused = client.post(reverse(DRAFT), {"step": "1", "strict": "0"})
        assert refused.status_code == 403


class TestScanPhotoIsTakenOnlyOnce:
    def test_both_photo_fields_tell_the_member_the_scan_photo_is_reused(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        assert html.count("data-image-hint") == 2 and "inutile d&#x27;en prendre une autre" in html or html.count("inutile d'en prendre une autre") == 1
        assert 'name="beer-image"' in html and 'name="drink-photo"' in html


class TestBeerPhotoIsReusedForTheReview:
    def test_the_hints_explain_the_reuse(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        assert "illustre aussi votre avis à l" in html and "Même photo que celle de la bière" in html
