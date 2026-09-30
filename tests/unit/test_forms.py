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

    def test_image_field_is_hidden_for_users_without_brewery(self, user):
        assert "image" not in BeerForm(user=user).fields

    def test_image_field_is_shown_to_brewery_managers(self, user):
        f.make_brewery(managers=[user])
        assert "image" in BeerForm(user=user).fields

    def test_image_field_on_edit_requires_managing_that_beer_brewery(self, user, beer):
        f.make_brewery(managers=[user])
        assert "image" not in BeerForm(instance=beer, user=user).fields
        beer.brewery_id.managers.add(user)
        assert "image" in BeerForm(instance=beer, user=user).fields

    def test_image_upload_for_a_brewery_not_managed_is_rejected(self, user, brewery):
        f.make_brewery(name="Ma Brasserie", managers=[user])
        form = BeerForm(data=beer_data(brewery_name=brewery.name), files={"image": f.make_image_upload()}, user=user)
        assert not form.is_valid()
        assert "image" in form.errors

    def test_image_upload_for_a_managed_brewery_is_accepted(self, user):
        f.make_brewery(name="Ma Brasserie", managers=[user])
        form = BeerForm(data=beer_data(brewery_name="ma brasserie"), files={"image": f.make_image_upload()}, user=user)
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
        return {"name": "Etablissement", "siret": "12345678901234", "description": "Desc", **overrides}

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
