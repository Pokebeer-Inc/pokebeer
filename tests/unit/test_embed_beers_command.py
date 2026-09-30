from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from app.models import Beer
from app.services import ai
from tests import factories as f

pytestmark = pytest.mark.django_db

VECTOR = [1.0] + [0.0] * 3071


def run(*args):
    out = StringIO()
    call_command("embed_beers", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def embedder(monkeypatch):
    calls = []

    def fake(text):
        calls.append(text)
        return VECTOR

    monkeypatch.setattr("app.management.commands.embed_beers.get_embedding", fake)
    return calls


def test_missing_api_key_is_refused(settings):
    settings.GEMINI_API_KEY = ""
    with pytest.raises(CommandError):
        run()


def test_only_beers_without_embedding_are_computed(embedder, monkeypatch):
    missing = f.make_beer(name="Sans vecteur")
    f.make_beer(name="Supprimée", is_deleted=True)
    monkeypatch.setattr(ai, "get_embedding", lambda text: VECTOR)
    f.make_beer(name="Déjà vectorisée")

    assert "1 bière(s)" in run()
    assert embedder == [missing.embedding_text]
    assert Beer.objects.get(pk=missing.pk).embedding is not None


def test_all_option_recomputes_every_active_beer(embedder, monkeypatch):
    monkeypatch.setattr(ai, "get_embedding", lambda text: VECTOR)
    f.make_beer()
    f.make_beer()
    run("--all")
    assert len(embedder) == 2


def test_failures_are_reported_and_left_for_a_retry(monkeypatch):
    monkeypatch.setattr("app.management.commands.embed_beers.get_embedding", lambda text: None)
    beer = f.make_beer()
    assert "1 échec(s)" in run()
    assert Beer.objects.get(pk=beer.pk).embedding is None
