import json
from unittest import mock

import pytest
from django.core.cache import cache

from app.services.chat import ChatBusy, ChatUnavailable, engine
from app.services.chat.tools import FindPlacesTool
from tests.fakes import chat_reply, http_error, tool_call, tool_reply


def text_reply(text):
    return chat_reply(text)


class FakeTool(FindPlacesTool):
    """Vraie déclaration, exécution factice."""

    def __init__(self, result=None, error=None):
        super().__init__(None)
        self.run = mock.Mock(return_value=result or {"places": []}, side_effect=error)


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()


@pytest.fixture
def client():
    return mock.Mock()


def ask(client, tools=None, history=(), full=False):
    reply = engine.converse(client, "système", list(history), "Où boire une Guinness ?", tools if tools is not None else {})
    return reply if full else reply.text


def sent(client, call_index=-1):
    return client.chat.complete.call_args_list[call_index].kwargs


def tool_messages(client):
    """Réponses d'outils envoyées au modèle (la liste de messages est la même d'un tour à l'autre : on lit son état final)."""
    return [message for message in sent(client)["messages"] if message["role"] == "tool"]


class TestConverse:
    def test_plain_answer_needs_a_single_call(self, client):
        client.chat.complete.return_value = text_reply("Une IPA !")
        assert ask(client) == "Une IPA !"
        assert client.chat.complete.call_count == 1

    def test_tool_result_is_given_back_to_the_model_then_the_answer_is_returned(self, client):
        tool = FakeTool({"places": [{"name": "Pub"}]})
        client.chat.complete.side_effect = [tool_reply("find_places"), text_reply("Allez au Pub")]
        assert ask(client, {"find_places": tool}) == "Allez au Pub"
        tool.run.assert_called_once_with({"keyword": "guinness"})
        (message,) = tool_messages(client)
        assert message["name"] == "find_places" and message["tool_call_id"] == "call-0"
        assert json.loads(message["content"]) == {"places": [{"name": "Pub"}]}

    def test_the_assistant_call_is_echoed_before_its_result(self, client):
        client.chat.complete.side_effect = [tool_reply("find_places"), text_reply("Fin")]
        ask(client, {"find_places": FakeTool()})
        roles = [message["role"] for message in sent(client)["messages"]]
        assert roles == ["system", "user", "assistant", "tool"]
        assert sent(client)["messages"][2]["tool_calls"][0]["function"]["name"] == "find_places"

    def test_a_model_that_keeps_calling_tools_is_stopped_and_the_last_round_has_no_tools(self, client):
        client.chat.complete.side_effect = [tool_reply("find_places")] * engine.MAX_TOOL_ROUNDS + [text_reply("Fin")]
        assert ask(client, {"find_places": FakeTool()}) == "Fin"
        calls = client.chat.complete.call_args_list
        assert all("tools" in call.kwargs for call in calls[:-1]) and "tools" not in calls[-1].kwargs

    def test_unknown_tool_and_excess_calls_are_answered_but_not_executed(self, client):
        tool = FakeTool()
        client.chat.complete.side_effect = [tool_reply("rm_rf", "find_places", "find_places"), text_reply("Ok")]
        ask(client, {"find_places": tool})
        assert tool.run.call_count == 1
        answers = [json.loads(message["content"]) for message in tool_messages(client)]
        assert answers == [{"error": "Outil inconnu."}, {"places": []}, engine.TOO_MANY_CALLS]

    def test_malformed_tool_arguments_are_treated_as_empty(self, client):
        tool = FakeTool()
        client.chat.complete.side_effect = [tool_reply(tool_call(arguments="{pas du json")), text_reply("Ok")]
        ask(client, {"find_places": tool})
        tool.run.assert_called_once_with({})

    def test_arguments_given_as_an_object_are_accepted(self, client):
        tool = FakeTool()
        client.chat.complete.side_effect = [tool_reply(tool_call(arguments={"kind": "bar"})), text_reply("Ok")]
        ask(client, {"find_places": tool})
        tool.run.assert_called_once_with({"kind": "bar"})

    def test_a_failing_tool_does_not_break_the_conversation(self, client):
        client.chat.complete.side_effect = [tool_reply("find_places"), text_reply("Désolé, pas de liste")]
        assert ask(client, {"find_places": FakeTool(error=RuntimeError("boom"))}) == "Désolé, pas de liste"
        assert json.loads(tool_messages(client)[0]["content"]) == engine.TOOL_FAILED

    def test_model_outage_is_reported(self, client):
        client.chat.complete.side_effect = TimeoutError
        with pytest.raises(ChatUnavailable):
            ask(client)
        assert client.chat.complete.call_count == 1  # un délai dépassé ne se rejoue pas sur chaque modèle

    @pytest.mark.parametrize("text", [None, "", "   ", "![x](https://evil.test/a)"])
    def test_blocked_or_empty_answers_get_a_polite_fallback(self, client, text):
        client.chat.complete.return_value = text_reply(text)
        assert ask(client) == engine.BLOCKED_REPLY

    def test_an_answer_made_of_chunks_is_read_as_text(self, client):
        from types import SimpleNamespace
        client.chat.complete.return_value = text_reply([SimpleNamespace(type="text", text="Une "), SimpleNamespace(type="text", text="IPA")])
        assert ask(client) == "Une IPA"

    def test_dangerous_output_is_sanitised(self, client):
        client.chat.complete.return_value = text_reply("Voir [ici](https://evil.test) ![](https://evil.test/p.png)")
        assert ask(client) == "Voir ici"

    def test_call_is_bounded_and_asks_for_the_provider_safety_prompt(self, client, settings):
        client.chat.complete.return_value = text_reply("ok")
        ask(client)
        call = sent(client)
        assert call["model"] == settings.CHAT_MODELS[0]
        assert call["max_tokens"] == settings.CHAT_MAX_OUTPUT_TOKENS
        assert call["timeout_ms"] == settings.CHAT_GENERATION_TIMEOUT_MS
        assert call["safe_prompt"] is True and "tools" not in call

    def test_tools_are_declared_as_json_schema_functions(self, client):
        client.chat.complete.return_value = text_reply("ok")
        ask(client, {"find_places": FakeTool()})
        (spec,) = sent(client)["tools"]
        assert spec["type"] == "function" and spec["function"]["name"] == "find_places"
        assert spec["function"]["parameters"]["type"] == "object" and sent(client)["tool_choice"] == "auto"

    def test_history_precedes_the_new_message(self, client):
        client.chat.complete.return_value = text_reply("ok")
        ask(client, history=[{"role": "user", "text": "Salut"}, {"role": "model", "text": "Bonjour"}])
        roles = [message["role"] for message in sent(client)["messages"]]
        assert roles == ["system", "user", "assistant", "user"]

    def test_a_missing_position_is_flagged_for_the_browser(self, client):
        no_position = FakeTool({"error": "x", "needs_location": True})
        client.chat.complete.side_effect = [tool_reply("find_places"), text_reply("jamais lu")]
        reply = ask(client, {"find_places": no_position}, full=True)
        assert reply.needs_location is True and reply.text == engine.NEEDS_LOCATION_REPLY
        assert client.chat.complete.call_count == 1  # pas de second appel : le navigateur renverra la demande avec la position

    def test_a_search_that_worked_is_answered_by_the_model(self, client):
        client.chat.complete.side_effect = [tool_reply("find_places"), text_reply("Réponse")]
        reply = ask(client, {"find_places": FakeTool({"places": []})}, full=True)
        assert reply.needs_location is False and reply.text == "Réponse"
        assert client.chat.complete.call_count == 2

    def test_a_normal_answer_does_not_ask_for_the_position(self, client):
        client.chat.complete.return_value = text_reply("Une IPA !")
        assert ask(client, full=True).needs_location is False

    def test_a_rate_limited_model_is_reported_as_busy_once_every_model_is_tried(self, client, settings):
        client.chat.complete.side_effect = http_error(429)
        with pytest.raises(ChatBusy):
            ask(client)
        assert client.chat.complete.call_count == len(settings.CHAT_MODELS)

    def test_the_next_model_takes_over_when_the_first_is_saturated(self, client, settings):
        client.chat.complete.side_effect = [http_error(429), text_reply("Via le second")]
        assert ask(client) == "Via le second"
        models = [call.kwargs["model"] for call in client.chat.complete.call_args_list]
        assert models == list(settings.CHAT_MODELS[:2])

    def test_a_bad_request_is_not_retried_on_other_models(self, client):
        client.chat.complete.side_effect = http_error(400)
        with pytest.raises(ChatUnavailable):
            ask(client)
        assert client.chat.complete.call_count == 1

    def test_every_model_call_is_reserved_first(self, client):
        reserve = mock.Mock(return_value=True)
        client.chat.complete.side_effect = [tool_reply("find_places"), text_reply("Fin")]
        engine.converse(client, "système", [], "Où ?", {"find_places": FakeTool()}, reserve)
        assert reserve.call_count == 2

    def test_a_refused_reservation_never_reaches_the_model(self, client):
        with pytest.raises(ChatBusy):
            engine.converse(client, "système", [], "Où ?", {}, mock.Mock(return_value=False))
        client.chat.complete.assert_not_called()

    def test_a_model_whose_minute_budget_is_spent_is_left_to_the_next_one(self, client, settings):
        client.chat.complete.return_value = text_reply("Via le suivant")
        first = settings.CHAT_MODELS[0]
        reply = engine.converse(client, "système", [], "Où ?", {}, lambda model: model != first)
        assert reply.text == "Via le suivant"
        assert client.chat.complete.call_args.kwargs["model"] == settings.CHAT_MODELS[1]

    def test_a_saturated_model_is_skipped_for_a_while(self, client, settings):
        client.chat.complete.side_effect = [http_error(429), text_reply("Un"), text_reply("Deux")]
        ask(client)
        ask(client)
        models = [call.kwargs["model"] for call in client.chat.complete.call_args_list]
        assert models == [settings.CHAT_MODELS[0], settings.CHAT_MODELS[1], settings.CHAT_MODELS[1]]
