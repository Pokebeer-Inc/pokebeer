from types import SimpleNamespace
from unittest import mock

import pytest

from app.services.chat import ChatUnavailable, engine
from app.services.chat.tools import FindPlacesTool
from tests.unit.test_ai_service import gemini  # noqa: F401  (client Gemini factice)


def text_reply(text):
    return SimpleNamespace(text=text, function_calls=None, candidates=[])


def tool_reply(*names):
    calls = [SimpleNamespace(name=name, args={"keyword": "guinness"}) for name in names]
    return SimpleNamespace(text=None, function_calls=calls, candidates=[SimpleNamespace(content=f"appel:{','.join(names)}")])


class FakeTool(FindPlacesTool):
    """Vraie déclaration (validée par le SDK), exécution factice."""

    def __init__(self, result=None, error=None):
        super().__init__(None)
        self.run = mock.Mock(return_value=result or {"places": []}, side_effect=error)


@pytest.fixture
def client():
    return mock.Mock()


def ask(client, tools=None, history=()):
    return engine.converse(client, "système", list(history), "Où boire une Guinness ?", tools if tools is not None else {})


def tool_responses(client, call_index):
    contents = client.models.generate_content.call_args_list[call_index].kwargs["contents"]
    return [part.function_response for part in contents[-1].parts]


class TestConverse:
    def test_plain_answer_needs_a_single_call(self, client):
        client.models.generate_content.return_value = text_reply("Une IPA !")
        assert ask(client) == "Une IPA !"
        assert client.models.generate_content.call_count == 1

    def test_tool_result_is_given_back_to_the_model_then_the_answer_is_returned(self, client):
        tool = FakeTool({"places": [{"name": "Pub"}]})
        client.models.generate_content.side_effect = [tool_reply("find_places"), text_reply("Allez au Pub")]
        assert ask(client, {"find_places": tool}) == "Allez au Pub"
        tool.run.assert_called_once_with({"keyword": "guinness"})
        (response,) = tool_responses(client, 1)
        assert response.name == "find_places" and response.response == {"places": [{"name": "Pub"}]}

    def test_a_model_that_keeps_calling_tools_is_stopped_and_the_last_round_has_no_tools(self, client):
        client.models.generate_content.side_effect = [tool_reply("find_places")] * engine.MAX_TOOL_ROUNDS + [text_reply("Fin")]
        assert ask(client, {"find_places": FakeTool()}) == "Fin"
        configs = [call.kwargs["config"] for call in client.models.generate_content.call_args_list]
        assert all(config.tools for config in configs[:-1]) and configs[-1].tools is None

    def test_unknown_tool_and_excess_calls_are_answered_but_not_executed(self, client):
        tool = FakeTool()
        client.models.generate_content.side_effect = [tool_reply("rm_rf", "find_places", "find_places"), text_reply("Ok")]
        ask(client, {"find_places": tool})
        assert tool.run.call_count == 1
        answers = [response.response for response in tool_responses(client, 1)]
        assert answers == [{"error": "Outil inconnu."}, {"places": []}, engine.TOO_MANY_CALLS]

    def test_a_failing_tool_does_not_break_the_conversation(self, client):
        client.models.generate_content.side_effect = [tool_reply("find_places"), text_reply("Désolé, pas de liste")]
        assert ask(client, {"find_places": FakeTool(error=RuntimeError("boom"))}) == "Désolé, pas de liste"
        assert tool_responses(client, 1)[0].response == engine.TOOL_FAILED

    def test_model_outage_is_reported(self, client):
        client.models.generate_content.side_effect = TimeoutError
        with pytest.raises(ChatUnavailable):
            ask(client)

    @pytest.mark.parametrize("text", [None, "", "   ", "![x](https://evil.test/a)"])
    def test_blocked_or_empty_answers_get_a_polite_fallback(self, client, text):
        client.models.generate_content.return_value = text_reply(text)
        assert ask(client) == engine.BLOCKED_REPLY

    def test_dangerous_output_is_sanitised(self, client):
        client.models.generate_content.return_value = text_reply("Voir [ici](https://evil.test) ![](https://evil.test/p.png)")
        assert ask(client) == "Voir ici"

    def test_call_is_bounded_and_not_open_to_unsafe_content(self, client, settings):
        client.models.generate_content.return_value = text_reply("ok")
        ask(client)
        call = client.models.generate_content.call_args.kwargs
        config = call["config"]
        assert call["model"] == settings.CHAT_MODEL
        assert config.max_output_tokens == settings.CHAT_MAX_OUTPUT_TOKENS
        assert config.http_options.timeout == settings.CHAT_GENERATION_TIMEOUT_MS
        assert config.automatic_function_calling.disable is True
        assert len(config.safety_settings) == 4 and config.thinking_config.thinking_budget == 0

    def test_history_precedes_the_new_message(self, client):
        client.models.generate_content.return_value = text_reply("ok")
        ask(client, history=[{"role": "user", "text": "Salut"}, {"role": "model", "text": "Bonjour"}])
        roles = [content.role for content in client.models.generate_content.call_args.kwargs["contents"]]
        assert roles == ["user", "model", "user"]
