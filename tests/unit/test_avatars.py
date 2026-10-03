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


def test_template_filter():
    html = Template("{% load avatars %}<img src='{{ name|initials_avatar }}'>").render(Context({"name": "Test"}))
    assert "data:image/svg+xml," in html and "ui-avatars" not in html
