from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.services.assistant import llm
from app.services.protection.throttle import Rule
from tests.fakes import embeddings_reply, http_error, search_reply

pytestmark = pytest.mark.django_db


class TestEmbed:
    def test_many_texts_are_sent_in_batches_and_come_back_in_order(self, mistral, monkeypatch):
        monkeypatch.setattr(llm, "EMBED_BATCH_SIZE", 2)
        mistral.embeddings.create.side_effect = lambda model, inputs, **kwargs: embeddings_reply(len(inputs))
        assert len(llm.embed(["a", "b", "c", "d", "e"], budgeted=False)) == 5
        assert [len(call.kwargs["inputs"]) for call in mistral.embeddings.create.call_args_list] == [2, 2, 1]

    def test_no_text_means_no_call(self, mistral):
        assert llm.embed([]) == []
        mistral.embeddings.create.assert_not_called()

    def test_a_wrong_number_of_vectors_is_refused(self, mistral):
        mistral.embeddings.create.side_effect = lambda model, inputs, **kwargs: embeddings_reply(len(inputs) + 1)
        assert llm.embed(["a"]) is None

    def test_a_spent_budget_skips_the_call_for_member_driven_embeddings(self, mistral, monkeypatch, settings):
        monkeypatch.setattr(llm, "CHAT_MODEL_CALLS", Rule("chat-model-calls", 1, timedelta(minutes=1)))
        assert llm.embed(["a"]) is not None
        assert llm.embed(["b"]) is None
        assert mistral.embeddings.create.call_count == 1

    def test_the_batch_mode_ignores_the_budget(self, mistral, monkeypatch):
        monkeypatch.setattr(llm, "CHAT_MODEL_CALLS", Rule("chat-model-calls", 0, timedelta(minutes=1)))
        assert llm.embed(["a"], budgeted=False) is not None

    def test_a_provider_error_is_swallowed_and_logged_without_content(self, mistral, caplog):
        mistral.embeddings.create.side_effect = http_error(429)
        assert llm.embed(["texte secret du membre"]) is None
        assert "texte secret" not in caplog.text


class TestHelpers:
    def test_the_budget_is_counted_per_model(self, monkeypatch):
        monkeypatch.setattr(llm, "CHAT_MODEL_CALLS", Rule("chat-model-calls", 1, timedelta(minutes=1)))
        assert llm.reserve_call("a") and not llm.reserve_call("a") and llm.reserve_call("b")

    def test_text_of_reads_strings_and_chunks_only(self):
        chunks = [SimpleNamespace(type="text", text="Bon"), SimpleNamespace(type="tool_reference", title="x"), SimpleNamespace(text="jour")]
        assert llm.text_of("Salut") == "Salut" and llm.text_of(chunks) == "Bonjour" and llm.text_of(None) == ""

    def test_the_last_written_answer_of_a_conversation_is_used(self):
        assert llm.conversation_text(search_reply("réponse")) == "réponse"
        assert llm.conversation_text(SimpleNamespace(outputs=[])) == ""

    def test_status_code_of_errors(self):
        assert llm.status_code(http_error(503)) == 503 and llm.status_code(RuntimeError()) is None
