import re

import pytest
from django.urls import reverse

from app.forms import BeerForm
from app.models import Beer, Drinks, Notification
from tests import factories as f
from tests.helpers import assert_redirects, messages_of

pytestmark = pytest.mark.django_db


def add_beer_data(name="Nouvelle Blonde", brewery_name="Brasserie Test", **overrides):
    return {
        "beer-name": name, "beer-brewery_name": brewery_name, "beer-degree": "6.5", "beer-style": "blonde",
        "drink-date": "2026-01-15", "drink-note": "8", "drink-comment": "Fruitée",
        **overrides,
    }


def edit_data(beer, **overrides):
    return {"name": beer.name, "brewery_name": beer.brewery_id.name, "degree": "7.0", "style": "IPA", **overrides}


class TestAddBeer:
    URL = reverse("add_beer")

    def test_form_is_prefilled_with_brewery_from_query_string(self, auth_client):
        response = auth_client.get(self.URL, {"brewery": "Mont Blanc"})
        assert response.context["beer_form"].initial["brewery_name"] == "Mont Blanc"

    def test_creates_beer_and_first_tasting(self, auth_client, user, brewery):
        assert_redirects(auth_client.post(self.URL, add_beer_data()), reverse("index"))
        beer = Beer.objects.get(name="Nouvelle Blonde")
        assert (beer.added_by, beer.brewery_id, beer.style) == (user, brewery, "Blonde")
        assert Drinks.objects.get().drinker_id == user

    def test_followers_and_brewery_managers_are_notified(self, auth_client, user, other_user, brewery):
        manager = f.make_user()
        brewery.managers.add(manager)
        f.follow(other_user, user)
        auth_client.post(self.URL, add_beer_data())
        assert set(Notification.objects.exclude(notif_type="achievement").values_list("recipient__username", "notif_type")) == {
            ("bobby", "beer_added"), (manager.username, "beer_added_to_brewery"),
        }

    def test_creator_managing_the_brewery_is_not_self_notified(self, auth_client, user, brewery):
        brewery.managers.add(user)
        auth_client.post(self.URL, add_beer_data())
        assert not Notification.objects.exclude(notif_type="achievement").exists()

    def test_tasting_can_only_be_filed_in_own_notebooks(self, auth_client, user, other_user):
        mine, foreign = f.make_notebook(user), f.make_notebook(other_user)
        auth_client.post(self.URL, add_beer_data(notebooks=[mine.slug, foreign.slug]))
        drink = Drinks.objects.get()
        assert list(drink.notebooks.all()) == [mine]

    @pytest.mark.parametrize("overrides", [{"beer-name": "test ipa"}, {"beer-degree": "101"}, {"drink-note": "11"}, {"drink-comment": ""}])
    def test_invalid_submission_creates_nothing(self, auth_client, beer, overrides):
        response = auth_client.post(self.URL, add_beer_data(**overrides))
        assert response.status_code == 200
        assert (Beer.objects.count(), Drinks.objects.count()) == (1, 0)


class TestReAddSoftDeletedBeer:
    URL = reverse("add_beer")

    @pytest.fixture
    def deleted(self, beer, other_user):
        f.make_drink(other_user, beer)
        Beer.objects.filter(pk=beer.pk).update(is_deleted=True)
        return beer

    def test_can_be_added_again_as_a_new_beer(self, auth_client, user, deleted):
        assert_redirects(auth_client.post(self.URL, add_beer_data(name="Test IPA")), reverse("index"))
        new = Beer.objects.get(name="Test IPA", is_deleted=False)
        assert new.pk != deleted.pk and new.slug.startswith("test-ipa-") and new.slug != deleted.slug and new.added_by == user

    def test_deleted_beer_keeps_its_url_and_tastings(self, auth_client, deleted):
        auth_client.post(self.URL, add_beer_data(name="Test IPA"))
        old = Beer.objects.get(pk=deleted.pk)
        assert (old.slug, old.is_deleted, Drinks.objects.filter(beer_id=old).count()) == (deleted.slug, True, 1)

    def test_re_added_beer_is_still_protected_against_duplicates(self, auth_client, deleted):
        auth_client.post(self.URL, add_beer_data(name="Test IPA"))
        response = auth_client.post(self.URL, add_beer_data(name="TEST  ipa"))
        assert response.status_code == 200
        assert Beer.objects.filter(is_deleted=False, name__iexact="test ipa").count() == 1


class TestAddBeerErrors:
    URL = reverse("add_beer")

    def submit(self, client, **overrides):
        return client.post(self.URL, add_beer_data(**overrides))

    def test_user_is_told_why_it_failed(self, auth_client, beer):
        response = self.submit(auth_client, **{"beer-name": "test ipa", "drink-note": "11"})
        message = " ".join(messages_of(response))
        assert "n'a pas pu être ajoutée" in message
        assert "Nom de la bière : Cette bière existe déjà sous le nom 'Test IPA'" in message
        assert "Note (sur 10)" in message

    def test_invalid_fields_are_emptied_and_highlighted_valid_ones_kept(self, auth_client, beer):
        response = self.submit(auth_client, **{"beer-name": "test ipa", "beer-degree": "101"})
        beer_form = response.context["beer_form"]
        assert (beer_form["name"].value(), beer_form["degree"].value()) == ("", "")
        assert beer_form["brewery_name"].value() == "Brasserie Test"
        assert response.context["drink_form"]["comment"].value() == "Fruitée"
        assert beer_form.fields["name"].widget.attrs["aria-invalid"] == "true"
        assert 'aria-invalid="true"' in str(beer_form["degree"]) and 'aria-invalid' not in str(beer_form["style"])

    def test_reasons_are_displayed_next_to_the_fields(self, auth_client, beer):
        html = self.submit(auth_client, **{"drink-comment": ""}).content.decode()
        assert 'role="alert"' in html and "Ce champ est obligatoire." in html

    def test_errors_of_both_forms_are_reported_together(self, auth_client, beer):
        response = self.submit(auth_client, **{"beer-name": "test ipa", "drink-comment": ""})
        assert set(response.context["beer_form"].errors) == {"name"}
        assert set(response.context["drink_form"].errors) == {"comment"}

    def test_selected_notebooks_stay_ticked(self, auth_client, user, beer):
        notebook = f.make_notebook(user)
        response = self.submit(auth_client, **{"beer-name": "test ipa", "notebooks": [notebook.slug, "abc"]})
        assert response.context["current_drink"] == {"notebook_slugs": [notebook.slug]}
        assert re.search(rf'name="notebooks" value="{notebook.slug}"[^>]*checked', response.content.decode())

    def test_name_taken_between_validation_and_save_is_reported_without_crash(self, auth_client, monkeypatch, brewery):
        # Simule deux soumissions validées au même instant : seules les vérifications en base restent actives
        monkeypatch.setattr(BeerForm, "clean_name", lambda form: form.cleaned_data["name"])
        monkeypatch.setattr(Beer, "validate_constraints", lambda self, exclude=None: None)
        f.make_beer(name="Nouvelle Blonde")

        response = self.submit(auth_client)

        assert response.status_code == 200
        assert "vient d'être ajoutée" in " ".join(messages_of(response))
        assert (Beer.objects.count(), Drinks.objects.count()) == (1, 0)


class TestBeerDetail:
    def test_unknown_slug_is_404(self, auth_client):
        assert auth_client.get(reverse("beer_detail", args=["nope"])).status_code == 404

    def test_reviews_are_sorted_by_score_and_hide_blocked_users(self, auth_client, user, beer):
        popular, unpopular, hidden = (f.make_drink(f.make_user(), beer) for _ in range(3))
        f.react(user, popular, is_like=True)
        f.react(user, unpopular, is_like=False)
        f.block(user, hidden.drinker_id)

        drinks = list(auth_client.get(reverse("beer_detail", args=[beer.slug])).context["drinks"])

        assert drinks == [popular, unpopular]
        assert [d.user_reaction for d in drinks] == [True, False]

    def test_own_rating_and_manager_flag_are_exposed(self, auth_client, user, beer):
        drink = f.make_drink(user, beer, note=6)
        beer.brewery_id.managers.add(user)
        context = auth_client.get(reverse("beer_detail", args=[beer.slug])).context
        assert (context["user_rating"]["slug"], context["user_rating"]["note"]) == (drink.slug, 6)
        assert context["is_brewery_manager"]


class TestEditBeer:
    def url(self, beer):
        return reverse("edit_beer", args=[beer.slug])

    def test_stranger_cannot_edit(self, auth_client, beer):
        assert_redirects(auth_client.post(self.url(beer), edit_data(beer, degree="12")), reverse("beer_detail", args=[beer.slug]))
        beer.refresh_from_db()
        assert beer.degree == 5

    def test_creator_edits_and_other_tasters_are_notified(self, other_client, beer):
        taster = f.make_user()
        f.make_drink(taster, beer)
        other_client.post(self.url(beer), edit_data(beer))
        beer.refresh_from_db()
        assert beer.degree == 7
        assert list(Notification.objects.values_list("recipient", "notif_type")) == [(taster.id, "beer_updated")]

    def test_manager_edit_notifies_the_creator(self, auth_client, user, beer):
        beer.brewery_id.managers.add(user)
        auth_client.post(self.url(beer), edit_data(beer))
        assert Notification.objects.get().notif_type == "beer_updated_by_manager"

    def test_deleted_beer_cannot_be_edited(self, other_client, beer):
        Beer.objects.filter(pk=beer.pk).update(is_deleted=True)
        assert other_client.get(self.url(beer)).status_code == 404


class TestDeleteBeer:
    def url(self, beer):
        return reverse("delete_beer", args=[beer.slug])

    def test_stranger_cannot_delete(self, auth_client, beer):
        auth_client.post(self.url(beer))
        beer.refresh_from_db()
        assert not beer.is_deleted

    def test_get_does_not_delete(self, other_client, beer):
        other_client.get(self.url(beer))
        beer.refresh_from_db()
        assert not beer.is_deleted

    def test_creator_soft_deletes_and_keeps_tastings(self, other_client, user, beer):
        f.make_drink(user, beer)
        f.make_notification(user, "beer_shared", beer=beer)
        assert_redirects(other_client.post(self.url(beer)), reverse("index"))
        beer.refresh_from_db()
        assert beer.is_deleted
        assert Drinks.objects.filter(beer_id=beer).exists()
        assert not Notification.objects.filter(beer=beer).exists()

    def test_manager_deletion_notifies_creator_by_name(self, auth_client, user, beer):
        beer.brewery_id.managers.add(user)
        auth_client.post(self.url(beer))
        notification = Notification.objects.get(notif_type="beer_deleted_by_manager")
        assert (notification.recipient.username, notification.text_content) == ("bobby", "Test IPA")


class TestVerifiedBadge:
    def page(self, client, beer):
        return client.get(reverse("beer_detail", args=[beer.slug])).content.decode()

    def test_badge_is_shown_only_on_verified_beers(self, auth_client, beer):
        assert 'aria-label="Vérifiée"' not in self.page(auth_client, beer)
        beer.is_verified = True
        beer.save()
        assert 'aria-label="Vérifiée"' in self.page(auth_client, beer)

    def test_members_cannot_set_the_verified_flag_through_the_forms(self, auth_client, user, beer):
        beer.added_by = user
        beer.save()
        auth_client.post(reverse("edit_beer", args=[beer.slug]), {**edit_data(beer), "is_verified": "on", "verified_by": user.pk})
        beer.refresh_from_db()
        assert (beer.is_verified, beer.verified_by) == (False, None)
