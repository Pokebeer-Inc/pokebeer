"""Pseudo : identifiant public, donc format strict et unicité sans égard à la casse, y compris lors d'un changement."""
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from app.forms import ProUserForm, UserRegisterForm, UserUpdateForm
from app.models import BeerUser
from app.validators import username_validator
from tests import factories as f

pytestmark = pytest.mark.django_db


def register_data(username, **overrides):
    return {"username": username, "email": "new@example.test", "password1": f.PASSWORD, "password2": f.PASSWORD, **overrides}


def update_data(user, **overrides):
    return {"username": user.username, "email": user.email, "bio": "", **overrides}


VALID = ["abc", "Alice", "bob_42", "jean-luc", "a.b.c", "x" * 30]
INVALID = [
    "ab", "x" * 31, "", "ali ce", "ali/ce", "ali,ce", "ali\"ce", "ali<b>", "ali'ce", "ali;ce", "ali%20", "..", "-abc", ".abc",
    "jérôme", "аlice", "ａｌｉｃｅ", "ali‮ce", "ali\x00ce", "a@b.c", "a+b", "../admin", "\\\\server",
]


class TestFormat:
    @pytest.mark.parametrize("username", VALID)
    def test_valid_usernames_are_accepted(self, username):
        assert UserRegisterForm(data=register_data(username)).is_valid()

    @pytest.mark.parametrize("username", INVALID)
    def test_unsafe_usernames_are_refused_at_registration(self, username):
        form = UserRegisterForm(data=register_data(username))
        assert not form.is_valid() and "username" in form.errors

    @pytest.mark.parametrize("username", INVALID)
    def test_unsafe_usernames_are_refused_when_renaming(self, user, username):
        assert "username" in UserUpdateForm(data=update_data(user, username=username), instance=user).errors

    @pytest.mark.parametrize("username", ["ali ce", "ali/ce"])
    def test_unsafe_usernames_are_refused_for_pro_accounts(self, username):
        form = ProUserForm(data={"username": username, "email": "pro@example.test", "password": f.PASSWORD})
        assert "username" in form.errors


class TestValidator:
    @pytest.mark.parametrize("username", ["alice\n", " alice", "alice "])
    def test_surrounding_whitespace_and_trailing_newline_are_not_tolerated(self, username):
        with pytest.raises(ValidationError):
            username_validator(username)


class TestUniqueness:
    def test_exact_duplicate_is_refused_at_registration(self, user):
        assert "username" in UserRegisterForm(data=register_data("alice")).errors

    @pytest.mark.parametrize("typed", ["ALICE", "Alice", "aLiCe"])
    def test_case_variants_are_refused_at_registration(self, user, typed):
        assert "username" in UserRegisterForm(data=register_data(typed)).errors

    def test_renaming_to_an_existing_username_is_refused(self, user, other_user):
        form = UserUpdateForm(data=update_data(user, username="bobby"), instance=user)
        assert form.errors["username"] == ["Ce pseudo est déjà utilisé."]

    def test_renaming_to_a_case_variant_of_another_member_is_refused(self, user, other_user):
        assert "username" in UserUpdateForm(data=update_data(user, username="BOBBY"), instance=user).errors

    def test_keeping_or_recasing_ones_own_username_is_allowed(self, user):
        assert UserUpdateForm(data=update_data(user), instance=user).is_valid()
        assert UserUpdateForm(data=update_data(user, username="ALICE"), instance=user).is_valid()

    def test_database_refuses_case_insensitive_duplicates_even_without_a_form(self, user):
        with pytest.raises(IntegrityError), transaction.atomic():
            f.make_user(username="ALICE")

    def test_rename_is_applied_when_free(self, user):
        form = UserUpdateForm(data=update_data(user, username="alice2"), instance=user)
        assert form.is_valid()
        form.save()
        assert BeerUser.objects.filter(username="alice2").exists()
