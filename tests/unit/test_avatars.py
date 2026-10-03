from urllib.parse import unquote

import pytest
from django.template import Context, Template

from app.services.avatars import initials_avatar_url


def svg(username):
    return unquote(initials_avatar_url(username).removeprefix("data:image/svg+xml,"))


def test_avatar_shows_the_uppercase_initial():
    assert ">M</text>" in svg("mlm")


@pytest.mark.parametrize("username", ["", None, "  "])
def test_empty_username_falls_back_to_a_question_mark(username):
    assert ">?</text>" in svg(username)


def test_username_cannot_inject_markup():
    assert "<script" not in svg("<script>alert(1)</script>") and "&lt;" in svg("<script>")


def test_no_external_request_is_needed():
    assert initials_avatar_url("bob").startswith("data:image/svg+xml,")


class TestAvatarUrl:
    def test_falls_back_to_the_initial(self, user):
        assert user.avatar_url.startswith("data:image/svg+xml,")

    def test_google_picture_is_used_when_https(self, user):
        from allauth.socialaccount.models import SocialAccount
        SocialAccount.objects.create(user=user, provider="google", uid="1", extra_data={"picture": "https://lh3.example/p.jpg"})
        assert user.avatar_url == "https://lh3.example/p.jpg"

    @pytest.mark.parametrize("picture", ["javascript:alert(1)", "http://insecure.example/p.jpg", None, 42])
    def test_unsafe_google_picture_is_ignored(self, user, picture):
        from allauth.socialaccount.models import SocialAccount
        SocialAccount.objects.create(user=user, provider="google", uid="1", extra_data={"picture": picture})
        assert user.avatar_url.startswith("data:image/svg+xml,")

    def test_uploaded_picture_takes_precedence(self, user):
        from django.core.files.base import ContentFile
        user.avatar.save("x.webp", ContentFile(b"data"), save=False)
        assert user.avatar_url == user.avatar.url
