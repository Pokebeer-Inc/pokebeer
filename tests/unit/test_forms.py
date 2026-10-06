from datetime import date

import pytest

from app.forms import (
    BarProForm, BeerForm, BreweryProForm, DrinkForm, UserRegisterForm, UserUpdateForm, clear_invalid_fields, error_summary,
)
from app.models import Beer, Brewery
from tests import factories as f

pytestmark = pytest.mark.django_db


def beer_data(**overrides):
    return {"name": "Nouvelle Blonde", "brewery_name": "Brasserie Test", "degree": "5.5", **overrides}


class TestBeerFormDuplicates:
    @pytest.mark.parametrize("typed_name", ["Test IPA", "test ipa", "  TEST  I.P.A ", "Tëst IPA"])
    def test_name_variants_of_an_existing_beer_are_rejected(self, beer, typed_name):
        form = BeerForm(data=beer_data(name=typed_name))
        assert not form.is_valid()
        assert "Test IPA" in form.errors["name"][0]

    def test_soft_deleted_beer_does_not_block_the_name(self, beer):
        beer.is_deleted = True
        beer.save()
        assert BeerForm(data=beer_data(name="test ipa")).is_valid()

    def test_editing_a_beer_keeps_its_own_name_valid(self, beer):
        assert BeerForm(data=beer_data(name="Test IPA"), instance=beer).is_valid()

    def test_active_beer_with_a_suffixed_slug_still_blocks_its_name(self, beer):
        Beer.objects.filter(pk=beer.pk).update(is_deleted=True)
        f.make_beer(name="Test IPA")
        form = BeerForm(data=beer_data(name="test ipa"))
        assert not form.is_valid() and "Test IPA" in form.errors["name"][0]

    def test_beer_whose_slug_only_starts_the_same_does_not_block(self, beer):
        assert BeerForm(data=beer_data(name="Test")).is_valid()


class TestInvalidFieldsHelpers:
    def invalid_form(self):
        data = {f"beer-{key}": value for key, value in beer_data(name="", degree="101", style="stout").items()}
        form = BeerForm(data=data, prefix="beer")
        assert not form.is_valid()
        return form

    def test_invalid_fields_are_emptied_and_flagged_but_errors_kept(self):
        form = self.invalid_form()
        clear_invalid_fields(form)
        assert (form["name"].value(), form["degree"].value(), form["style"].value()) == ("", "", "stout")
        assert set(form.errors) == {"name", "degree"}
        assert "aria-invalid" not in form.fields["style"].widget.attrs

    def test_summary_prefixes_each_error_with_its_label(self):
        form = self.invalid_form()
        summary = error_summary(form)
        assert any(line.startswith("Nom de la bière : ") for line in summary)
        assert any(line.startswith("Alcool (%) : ") for line in summary)

    def test_summary_keeps_errors_without_field(self):
        form = self.invalid_form()
        form.add_error(None, "Erreur générale")
        assert "Erreur générale" in error_summary(form)


class TestBeerFormCleaning:
    @pytest.mark.parametrize("raw, expected", [
        ("ipa, DOUBLE IPA ,,stout", "Ipa, Double ipa, Stout"),
        ("  lager  ", "Lager"),
        (",,,", ""),
        ("", None),
    ])
    def test_style_is_normalised(self, brewery, raw, expected):
        form = BeerForm(data=beer_data(style=raw))
        assert form.is_valid(), form.errors
        assert form.cleaned_data["style"] == expected

    @pytest.mark.parametrize("field, value", [
        ("degree", "100.1"), ("degree", "-1"), ("bitterness", "501"), ("bitterness", "-1"), ("name", "x" * 151), ("name", ""),
    ])
    def test_out_of_range_values_are_rejected(self, field, value):
        assert field in BeerForm(data=beer_data(**{field: value})).errors

    @pytest.mark.parametrize("field, value", [("degree", "0"), ("degree", "99.9"), ("bitterness", "0"), ("bitterness", "500")])
    def test_limit_values_are_accepted(self, field, value):
        assert BeerForm(data=beer_data(**{field: value})).is_valid()


class TestBeerFormSave:
    def test_existing_brewery_is_reused_case_insensitively(self, brewery, user):
        beer = BeerForm(data=beer_data(brewery_name="BRASSERIE test")).save(user=user)
        assert beer.brewery_id == brewery
        assert beer.added_by == user
        assert Brewery.objects.count() == 1

    def test_unknown_brewery_is_created_on_the_fly(self, user):
        beer = BeerForm(data=beer_data(brewery_name="Inconnue")).save(user=user)
        assert beer.brewery_id.name == "Inconnue"
        assert beer.brewery_id.description == "Ajoutée automatiquement"


class TestBeerFormImagePermission:
    def test_image_field_is_hidden_for_anonymous_form(self):
        assert "image" not in BeerForm().fields

    def test_image_field_is_shown_to_the_author_of_a_new_beer(self, user):
        assert "image" in BeerForm(user=user).fields

    def test_creator_can_edit_the_image_until_the_beer_is_verified(self, user, other_user, beer):
        beer.added_by = user
        assert "image" in BeerForm(instance=beer, user=user).fields
        beer.is_verified = True
        assert "image" not in BeerForm(instance=beer, user=user).fields

    def test_brewery_manager_can_edit_the_image_even_when_verified(self, user, beer):
        beer.is_verified = True
        beer.brewery_id.managers.add(user)
        assert "image" in BeerForm(instance=beer, user=user).fields

    def test_a_stranger_cannot_edit_the_image(self, user, beer):
        assert "image" not in BeerForm(instance=beer, user=user).fields

    def test_remove_flag_is_ignored_when_the_image_field_is_not_allowed(self, user, beer):
        beer.image.save("x.webp", f.make_image_upload(), save=True)
        form = BeerForm(data=beer_data(name=beer.name, brewery_name=beer.brewery_id.name, remove_image="on"), instance=beer, user=user)
        assert form.is_valid(), form.errors
        form.save()
        beer.refresh_from_db()
        assert beer.image

    def test_uploaded_image_is_reencoded_with_a_random_name(self, user):
        form = BeerForm(data=beer_data(), files={"image": f.make_image_upload("../../evil.png")}, user=user)
        assert form.is_valid(), form.errors
        beer = form.save(user=user)
        assert beer.image.name.startswith("beers/") and beer.image.name.endswith(".webp") and "evil" not in beer.image.name

    def test_non_image_upload_is_rejected(self, user):
        from django.core.files.uploadedfile import SimpleUploadedFile
        form = BeerForm(data=beer_data(), files={"image": SimpleUploadedFile("a.png", b"not an image")}, user=user)
        assert not form.is_valid() and "image" in form.errors

    def test_image_is_replaced_and_old_file_deleted(self, user, beer, django_capture_on_commit_callbacks):
        beer.added_by = user
        beer.image.save("x.webp", f.make_image_upload(), save=True)
        old, storage = beer.image.name, beer.image.storage
        form = BeerForm(data=beer_data(name=beer.name, brewery_name=beer.brewery_id.name), files={"image": f.make_image_upload()}, instance=beer, user=user)
        assert form.is_valid(), form.errors
        with django_capture_on_commit_callbacks(execute=True):
            form.save()
        beer.refresh_from_db()
        assert beer.image.name != old and not storage.exists(old)

    def test_image_can_be_removed(self, user, beer, django_capture_on_commit_callbacks):
        beer.added_by = user
        beer.image.save("x.webp", f.make_image_upload(), save=True)
        old, storage = beer.image.name, beer.image.storage
        form = BeerForm(data=beer_data(name=beer.name, brewery_name=beer.brewery_id.name, remove_image="on"), instance=beer, user=user)
        assert form.is_valid(), form.errors
        with django_capture_on_commit_callbacks(execute=True):
            form.save()
        beer.refresh_from_db()
        assert not beer.image and not storage.exists(old)


class TestEmailUniqueness:
    @pytest.mark.parametrize("typed", ["alice@example.com", "ALICE@Example.com"])
    def test_register_refuses_an_email_whatever_its_case(self, user, typed):
        user.email = "alice@example.com"
        user.save()
        form = UserRegisterForm(data={"username": "nouveau", "email": typed, "password1": "Sup3r-Secret!x", "password2": "Sup3r-Secret!x"})
        assert not form.is_valid() and "email" in form.errors

    def test_update_refuses_the_email_of_another_member_whatever_its_case(self, user, other_user):
        other_user.email = "bob@example.com"
        other_user.save()
        form = UserUpdateForm(data={"username": user.username, "email": "BOB@example.com", "bio": ""}, instance=user)
        assert not form.is_valid() and "email" in form.errors

    def test_update_keeps_the_members_own_email(self, user):
        form = UserUpdateForm(data={"username": user.username, "email": user.email, "bio": ""}, instance=user)
        assert form.is_valid(), form.errors


class TestDrinkForm:
    @pytest.mark.parametrize("note, valid", [("", True), ("0", True), ("10", True), ("11", False), ("-1", False), ("7.5", False)])
    def test_note_is_optional_and_bounded(self, note, valid):
        form = DrinkForm(data={"date": "2026-01-01", "note": note, "comment": "ok"})
        assert form.is_valid() is valid

    def test_comment_is_required(self):
        assert "comment" in DrinkForm(data={"date": "2026-01-01", "note": "5", "comment": ""}).errors


class TestUserForms:
    PASSWORD = f.PASSWORD

    def register_data(self, **overrides):
        return {"username": "newbie", "email": "newbie@example.test", "password1": self.PASSWORD, "password2": self.PASSWORD, **overrides}

    def test_registration_is_valid(self):
        assert UserRegisterForm(data=self.register_data()).is_valid()

    @pytest.mark.parametrize("overrides, field", [
        ({"email": "alice@example.test"}, "email"),
        ({"username": "alice"}, "username"),
        ({"password2": "different-Passw0rd!"}, "password2"),
        ({"password1": "password", "password2": "password"}, "password2"),
        ({"password1": "12345678", "password2": "12345678"}, "password2"),
        ({"username": "x" * 151}, "username"),
        ({"email": "not-an-email"}, "email"),
    ], ids=["dup-email", "dup-username", "mismatch", "common-password", "numeric-password", "username-too-long", "bad-email"])
    def test_invalid_registration_is_rejected(self, user, overrides, field):
        assert field in UserRegisterForm(data=self.register_data(**overrides)).errors

    def test_profile_update_keeps_own_email(self, user):
        assert UserUpdateForm(data={"username": "alice", "email": user.email, "bio": ""}, instance=user).is_valid()

    def test_profile_update_cannot_steal_another_email(self, user, other_user):
        form = UserUpdateForm(data={"username": "alice", "email": other_user.email}, instance=user)
        assert "email" in form.errors


@pytest.mark.parametrize("form_class", [BarProForm, BreweryProForm])
class TestProForms:
    def data(self, **overrides):
        return {"name": "Etablissement", "siret": "73282932000074", "description": "Desc", **overrides}

    def test_valid_establishment(self, form_class):
        assert form_class(data=self.data()).is_valid()

    @pytest.mark.parametrize("siret", ["1234567890123", "123456789012345", ""])
    def test_siret_must_have_exactly_14_characters(self, form_class, siret):
        assert "siret" in form_class(data=self.data(siret=siret)).errors

    def test_siret_is_unique(self, form_class):
        form_class(data=self.data()).save()
        assert "siret" in form_class(data=self.data(name="Autre")).errors

    @pytest.mark.parametrize("field", ["website", "instagram", "facebook"])
    def test_social_links_must_be_urls(self, form_class, field):
        assert field in form_class(data=self.data(**{field: "javascript:alert(1)"})).errors


class TestTextAndDateLimits:
    def drink(self, **overrides):
        return DrinkForm(data={"date": "2026-01-01", "note": "5", "comment": "ok", **overrides})

    def test_comment_is_bounded(self):
        assert not self.drink(comment="x" * 2001).is_valid()
        assert self.drink(comment="x" * 2000).is_valid()

    @pytest.mark.parametrize("date", ["2999-01-01", "1800-01-01"])
    def test_implausible_dates_are_refused(self, date):
        assert "date" in self.drink(date=date).errors

    def test_an_already_saved_date_is_not_revalidated_on_edit(self, user, beer):
        drink = f.make_drink(user, beer)
        drink.date = date(1850, 1, 1)
        form = DrinkForm(data={"date": "1850-01-01", "note": "5", "comment": "ok"}, instance=drink)
        assert form.is_valid(), form.errors

    def test_bio_is_bounded(self, user):
        form = UserUpdateForm(data={"username": user.username, "email": user.email, "bio": "x" * 501}, instance=user)
        assert "bio" in form.errors
