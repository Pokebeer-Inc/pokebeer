"""Retour visuel pendant une attente : un seul module (pending.js), appelé par les actions qui font une requête."""
import shutil
import subprocess
from pathlib import Path

import pytest
from django.urls import reverse

SCRIPTS = Path("app/static/script")
CSS = Path("app/static/style/ui.css").read_text()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
def test_the_pending_module_behaves():
    result = subprocess.run(["node", "tests/js/pending_check.js"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr


@pytest.mark.django_db
def test_every_page_loads_the_module_before_the_page_loader(client, google_app):
    html = client.get(reverse("login")).content.decode()
    assert html.index("script/pending.js") < html.index("script/loader.js")


@pytest.mark.parametrize("script", [
    "wishlist.js", "like_dislike_drinks.js", "load_more_generic.js", "username_edit.js", "stepper.js", "add_beer_wizard.js", "chat.js", "top3_sort.js", "search.js",
])
def test_actions_that_wait_use_the_shared_module(script):
    assert "Pending." in (SCRIPTS / script).read_text()


def test_no_button_does_its_own_disabling_before_a_submit():
    offenders = [str(path) for path in Path("app/templates").rglob("*.html")
                 if "admin" not in path.parts and (".submit()" in path.read_text() or "this.disabled=true" in path.read_text())]
    assert offenders == []


def test_the_avatar_form_goes_through_the_page_loader():
    source = (SCRIPTS / "avatar_upload.js").read_text()
    assert "requestSubmit()" in source and ".submit()" not in source.replace("requestSubmit()", "")


def test_the_spinner_waits_a_moment_and_respects_reduced_motion():
    assert "pb-appear 0.15s 0.15s backwards" in CSS and "prefers-reduced-motion" in CSS.split(".pb-spinner", 1)[1]


def test_a_repeated_press_is_ignored_while_waiting():
    source = (SCRIPTS / "pending.js").read_text()
    assert "if (!element || element.dataset.pending) return false" in source


def test_back_navigation_never_leaves_something_pending():
    assert "pageshow" in (SCRIPTS / "pending.js").read_text()
