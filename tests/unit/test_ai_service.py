from types import SimpleNamespace
from unittest import mock

import pytest

from app.services import ai
from tests import factories as f

DIMENSIONS = 3072


def unit_vector(axis):
    vector = [0.0] * DIMENSIONS
    vector[axis] = 1.0
    return vector


@pytest.fixture
def gemini(monkeypatch):
    """Client Gemini factice injecté à la place du vrai SDK."""
    client = mock.Mock()
    client.models.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=unit_vector(0))])
    client.models.generate_content.return_value = SimpleNamespace(text="Essayez la Test IPA !")
    monkeypatch.setattr(ai, "config_client", lambda: client)
    return client


class TestGetEmbedding:
    def test_returns_vector_values(self, gemini):
        assert ai.get_embedding("IPA") == unit_vector(0)
        assert gemini.models.embed_content.call_args.kwargs["contents"] == "IPA"

    def test_missing_api_key_skips_the_call(self, settings, gemini):
        settings.GEMINI_API_KEY = None
        assert ai.get_embedding("IPA") is None
        gemini.models.embed_content.assert_not_called()

    def test_api_failure_returns_none(self):
        assert ai.get_embedding("IPA") is None


@pytest.mark.django_db
class TestBeersContext:
    def test_empty_catalogue(self):
        assert ai._format_beers_context("stout") is None

    def test_fallback_lists_at_most_ten_beers_with_unknown_values_labelled(self):
        for _ in range(12):
            f.make_beer(bitterness=None, style=None)
        lines = ai._format_beers_context("stout").splitlines()
        assert len(lines) == 10
        assert all("Style inconnu" in line and "IBU inconnu" in line for line in lines)

    def test_semantic_search_orders_by_cosine_distance_and_skips_deleted(self, monkeypatch):
        vectors = iter([unit_vector(1), unit_vector(0), unit_vector(0)])
        monkeypatch.setattr(ai, "get_embedding", lambda text: next(vectors))
        f.make_beer(name="Lointaine")
        f.make_beer(name="Proche")
        f.make_beer(name="Supprimée", is_deleted=True)

        monkeypatch.setattr(ai, "get_embedding", lambda text: unit_vector(0))
        lines = ai._format_beers_context("proche").splitlines()

        assert [line.split(" (")[0] for line in lines] == ["- Proche", "- Lointaine"]

    def test_beers_without_embedding_complete_the_semantic_results(self, monkeypatch):
        monkeypatch.setattr(ai, "get_embedding", lambda text: unit_vector(0))
        f.make_beer(name="Vectorisée")
        monkeypatch.setattr(ai, "get_embedding", lambda text: None)
        f.make_beer(name="Pas encore vectorisée")

        monkeypatch.setattr(ai, "get_embedding", lambda text: unit_vector(0))
        names = [line.split(" (")[0] for line in ai._format_beers_context("ipa").splitlines()]

        assert names == ["- Vectorisée", "- Pas encore vectorisée"]

    def test_catalogue_without_any_embedding_is_still_proposed(self, monkeypatch):
        for _ in range(ai.CONTEXT_SIZE + 2):
            f.make_beer()
        monkeypatch.setattr(ai, "get_embedding", lambda text: unit_vector(0))
        assert len(ai._format_beers_context("ipa").splitlines()) == ai.CONTEXT_SIZE


@pytest.mark.django_db
class TestAskZythologue:
    def test_inactive_without_api_key(self, settings):
        settings.GEMINI_API_KEY = ""
        assert "inactif" in ai.ask_zythologue("Bonjour")

    def test_sends_history_then_message_with_catalogue_in_system_prompt(self, gemini, beer):
        history = [{"role": "user", "text": "Salut"}, {"role": "model", "text": "Bonjour !"}]

        assert ai.ask_zythologue("Une IPA ?", history) == "Essayez la Test IPA !"

        call = gemini.models.generate_content.call_args.kwargs
        assert [(c.role, c.parts[0].text) for c in call["contents"]] == [("user", "Salut"), ("model", "Bonjour !"), ("user", "Une IPA ?")]
        assert "Test IPA" in call["config"].system_instruction

    def test_history_is_not_mutated(self, gemini):
        history = [{"role": "user", "text": "Salut"}]
        ai.ask_zythologue("Encore ?", history)
        assert history == [{"role": "user", "text": "Salut"}]

    def test_api_failure_returns_friendly_message(self):
        assert ai.ask_zythologue("Bonjour").startswith("Désolé")
