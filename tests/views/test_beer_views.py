
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
        **overrides,
    }


def edit_data(beer, **overrides):
    return {"name": beer.name, "brewery_name": beer.brewery.name, "degree": "7.0", "style": "IPA", **overrides}


class TestAddBeer:
    URL = reverse("add_beer")

    def test_form_is_prefilled_with_brewery_from_query_string(self, auth_client):
        response = auth_client.get(self.URL, {"brewery": "Mont Blanc"})
        assert response.context["beer_form"].initial["brewery_name"] == "Mont Blanc"

    def test_creates_the_beer_without_a_tasting(self, auth_client, user, brewery):
        response = auth_client.post(self.URL, add_beer_data())
        beer = Beer.objects.get(name="Nouvelle Blonde")
        assert_redirects(response, reverse("add_beer_done", args=[beer.slug]))
        assert (beer.added_by, beer.brewery, beer.style) == (user, brewery, "Blonde")
        assert not Drinks.objects.exists()  # la dégustation est un autre geste, proposé ensuite

    def test_the_brewery_is_optional(self, auth_client, user):
        auth_client.post(self.URL, add_beer_data(brewery_name=""))
        beer = Beer.objects.get(name="Nouvelle Blonde")
        assert beer.brewery is None and beer.added_by == user and beer.needs_review

    def test_a_new_brewery_is_created_when_it_is_typed(self, auth_client):
        auth_client.post(self.URL, add_beer_data(brewery_name="Brasserie Inconnue de tous"))
        assert Beer.objects.get(name="Nouvelle Blonde").brewery.name == "Brasserie Inconnue de tous"

    def test_nobody_is_notified_for_a_brewery_that_is_unknown(self, auth_client, user, other_user):
        f.follow(other_user, user)
        auth_client.post(self.URL, add_beer_data(brewery_name=""))
        assert set(Notification.objects.exclude(notif_type="achievement").values_list("notif_type", flat=True)) == {"beer_added"}

    def test_unbranded_beers_are_told_apart_by_their_degree(self, auth_client):
        auth_client.post(self.URL, {"beer-name": "La Blonde", "beer-degree": "5"})
        same = auth_client.post(self.URL, {"beer-name": "la  blonde", "beer-degree": "5.0"})
        other = auth_client.post(self.URL, {"beer-name": "La Blonde", "beer-degree": "6.5"})
        assert same.status_code == 200 and other.status_code == 302
        assert sorted(Beer.objects.filter(brewery__isnull=True).values_list("degree", flat=True)) == [5, 6.5]

    def test_an_unbranded_beer_with_the_name_of_a_branded_one_is_only_a_notice(self, auth_client, beer):
        response = auth_client.post(self.URL, {"beer-name": beer.name, "beer-degree": "5"})
        assert response.status_code == 302 and Beer.objects.filter(name=beer.name).count() == 2

    def test_the_database_has_the_last_word_on_unbranded_duplicates(self, db):
        from django.db import IntegrityError, transaction
        f.make_beer(name="Pinte", unbranded=True, degree=5)
        with pytest.raises(IntegrityError), transaction.atomic():
            f.make_beer(name="PINTE", unbranded=True, degree=5)

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

    @pytest.mark.parametrize("overrides", [{"beer-name": "test ipa"}, {"beer-degree": "101"}, {"beer-degree": ""}, {"beer-bitterness": "9999"}])
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
        response = auth_client.post(self.URL, add_beer_data(name="Test IPA"))
        new = Beer.objects.get(name="Test IPA", is_deleted=False)
        assert_redirects(response, reverse("add_beer_done", args=[new.slug]))
        assert new.pk != deleted.pk and new.slug.startswith("test-ipa-") and new.slug != deleted.slug and new.added_by == user

    def test_deleted_beer_keeps_its_url_and_tastings(self, auth_client, deleted):
        auth_client.post(self.URL, add_beer_data(name="Test IPA"))
        old = Beer.objects.get(pk=deleted.pk)
        assert (old.slug, old.is_deleted, Drinks.objects.filter(beer=old).count()) == (deleted.slug, True, 1)

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
        response = self.submit(auth_client, **{"beer-name": "test ipa", "beer-bitterness": "9999"})
        message = " ".join(messages_of(response))
        assert "n'a pas pu être ajoutée" in message
        assert "Cette bière existe déjà : « Test IPA » (Brasserie Test)." in message
        assert "IBU" in message

    def test_invalid_fields_are_emptied_and_highlighted_valid_ones_kept(self, auth_client, beer):
        response = self.submit(auth_client, **{"beer-name": "test ipa", "beer-degree": "101"})
        beer_form = response.context["beer_form"]
        # Le doublon est une erreur du formulaire (le nom reste modifiable) ; seul le champ invalide est vidé
        assert (beer_form["name"].value(), beer_form["degree"].value()) == ("test ipa", "")
        assert beer_form["brewery_name"].value() == "Brasserie Test"
        assert "aria-invalid" not in beer_form.fields["name"].widget.attrs and beer_form.fields["degree"].widget.attrs["aria-invalid"] == "true"
        assert 'aria-invalid="true"' in str(beer_form["degree"]) and 'aria-invalid' not in str(beer_form["style"])

    def test_reasons_are_displayed_next_to_the_fields(self, auth_client, beer):
        html = self.submit(auth_client, **{"beer-name": ""}).content.decode()
        assert 'role="alert"' in html and "Ce champ est obligatoire." in html

    def test_every_error_of_the_form_is_reported_together(self, auth_client, beer):
        response = self.submit(auth_client, **{"beer-name": "test ipa", "beer-bitterness": "9999"})
        assert set(response.context["beer_form"].errors) == {"__all__", "bitterness"}

    def test_name_taken_between_validation_and_save_is_reported_without_crash(self, auth_client, monkeypatch, brewery):
        # Simule deux soumissions validées au même instant : seules les vérifications en base restent actives
        monkeypatch.setattr(BeerForm, "clean", lambda form: form.cleaned_data)
        monkeypatch.setattr(Beer, "validate_constraints", lambda self, exclude=None: None)
        f.make_beer(name="Nouvelle Blonde", brewery=brewery)

        response = self.submit(auth_client)

        assert response.status_code == 200
        assert "vient d'être ajoutée" in " ".join(messages_of(response))
        assert Beer.objects.count() == 1


class TestBeerDetail:
    def test_unknown_slug_is_404(self, auth_client):
        assert auth_client.get(reverse("beer_detail", args=["nope"])).status_code == 404

    def test_reviews_are_sorted_by_score_and_hide_blocked_users(self, auth_client, user, beer):
        popular, unpopular, hidden = (f.make_drink(f.make_user(), beer) for _ in range(3))
        f.react(user, popular, is_like=True)
        f.react(user, unpopular, is_like=False)
        f.block(user, hidden.drinker)

        drinks = list(auth_client.get(reverse("beer_detail", args=[beer.slug])).context["drinks"])

        assert drinks == [popular, unpopular]
        assert [d.user_reaction for d in drinks] == [True, False]

    def test_own_rating_and_manager_flag_are_exposed(self, auth_client, user, beer):
        drink = f.make_drink(user, beer, note=6)
        beer.brewery.managers.add(user)
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
        beer.brewery.managers.add(user)
        auth_client.post(self.url(beer), edit_data(beer))
        assert Notification.objects.get().notif_type == "beer_updated_by_manager"

    def test_creator_can_no_longer_edit_a_verified_beer(self, other_client, beer):
        Beer.objects.filter(pk=beer.pk).update(is_verified=True)
        assert_redirects(other_client.post(self.url(beer), edit_data(beer, degree="12")), reverse("beer_detail", args=[beer.slug]))
        beer.refresh_from_db()
        assert beer.degree == 5

    def test_manager_can_still_edit_a_verified_beer(self, auth_client, user, beer):
        Beer.objects.filter(pk=beer.pk).update(is_verified=True)
        beer.brewery.managers.add(user)
        auth_client.post(self.url(beer), edit_data(beer))
        beer.refresh_from_db()
        assert beer.degree == 7

    def test_creator_changes_the_picture_and_the_old_one_is_deleted(self, other_client, beer, django_capture_on_commit_callbacks):
        other_client.post(self.url(beer), {**edit_data(beer), "image": f.make_image_upload()})
        beer.refresh_from_db()
        first, storage = beer.image.name, beer.image.storage
        assert first.startswith("beers/") and first.endswith(".webp")
        with django_capture_on_commit_callbacks(execute=True):
            other_client.post(self.url(beer), {**edit_data(beer), "image": f.make_image_upload()})
        beer.refresh_from_db()
        assert beer.image.name != first and not storage.exists(first)

    def test_editing_without_a_new_file_keeps_the_picture(self, other_client, beer):
        other_client.post(self.url(beer), {**edit_data(beer), "image": f.make_image_upload()})
        beer.refresh_from_db()
        name = beer.image.name
        other_client.post(self.url(beer), edit_data(beer))
        beer.refresh_from_db()
        assert beer.image.name == name

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
        assert Drinks.objects.filter(beer=beer).exists()
        assert not Notification.objects.filter(beer=beer).exists()

    def test_manager_deletion_notifies_creator_by_name(self, auth_client, user, beer):
        beer.brewery.managers.add(user)
        auth_client.post(self.url(beer))
        notification = Notification.objects.get(notif_type="beer_deleted_by_manager")
        assert (notification.recipient.username, notification.text_content) == ("bobby", "Test IPA")


    def test_creator_cannot_delete_a_verified_beer(self, other_client, beer):
        Beer.objects.filter(pk=beer.pk).update(is_verified=True)
        response = other_client.post(self.url(beer))
        beer.refresh_from_db()
        assert not beer.is_deleted
        assert "seul le gérant de la brasserie peut la retirer" in " ".join(messages_of(response))

    def test_manager_can_delete_a_verified_beer(self, auth_client, user, beer):
        Beer.objects.filter(pk=beer.pk).update(is_verified=True)
        beer.brewery.managers.add(user)
        auth_client.post(self.url(beer))
        beer.refresh_from_db()
        assert beer.is_deleted

    def test_the_menu_hides_actions_the_creator_can_no_longer_take(self, other_client, beer):
        Beer.objects.filter(pk=beer.pk).update(is_verified=True)
        html = other_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()
        assert reverse("edit_beer", args=[beer.slug]) not in html and 'data-modal-open="modal_confirm_beer"' not in html


class TestDeletedBeerVisibility:
    @pytest.fixture
    def deleted(self, beer):
        Beer.objects.filter(pk=beer.pk).update(is_deleted=True)
        return beer

    def page(self, client, beer):
        return client.get(reverse("beer_detail", args=[beer.slug]))

    def test_hidden_from_other_members_and_from_its_creator(self, auth_client, other_client, deleted):
        assert self.page(auth_client, deleted).status_code == 404
        assert self.page(other_client, deleted).status_code == 404  # le créateur, sans dégustation ni gestion

    def test_visible_to_members_who_tasted_it(self, auth_client, user, deleted):
        f.make_drink(user, deleted)
        assert self.page(auth_client, deleted).status_code == 200

    def test_visible_to_the_brewery_managers(self, auth_client, user, deleted):
        deleted.brewery.managers.add(user)
        assert self.page(auth_client, deleted).status_code == 200

    def test_no_new_rating(self, auth_client, user, deleted):
        response = auth_client.post(reverse("rate_beer", args=[deleted.slug]), {"note": 7, "comment": "Bonne", "date": "2026-01-01"})
        assert response.status_code == 404 and not Drinks.objects.filter(drinker=user).exists()


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
