"""Réponses factices de Mistral (même forme que le SDK) : aucun test ne joint le vrai service."""
from types import SimpleNamespace
from unittest import mock

DIMENSIONS = 1024


def unit_vector(axis):
    vector = [0.0] * DIMENSIONS
    vector[axis] = 1.0
    return vector


def chat_reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))])


def tool_call(name="find_places", arguments=None, call_id="call-1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments if arguments is not None else '{"keyword": "guinness"}'))


def tool_reply(*calls):
    """Réponse du modèle qui demande des outils (noms, ou appels construits avec `tool_call`)."""
    calls = [call if not isinstance(call, str) else tool_call(call, call_id=f"call-{index}") for index, call in enumerate(calls)]
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=calls))])


def search_reply(text):
    """Réponse de l'API Conversations (recherche web) : un message d'assistant dont le contenu mêle texte et références."""
    chunks = [SimpleNamespace(type="text", text=text), SimpleNamespace(type="tool_reference", title="Source", url="https://example.org")]
    return SimpleNamespace(outputs=[SimpleNamespace(type="tool.execution", name="web_search"), SimpleNamespace(type="message.output", content=chunks)])


def embeddings_reply(count=1, axis=0):
    return SimpleNamespace(data=[SimpleNamespace(embedding=unit_vector(axis)) for _ in range(count)])


def mistral(answer="Essayez la Test IPA !"):
    """Client Mistral factice : discussion, embeddings (un vecteur par texte) et recherche web."""
    client = mock.Mock()
    client.chat.complete.return_value = chat_reply(answer)
    client.embeddings.create.side_effect = lambda model, inputs, **kwargs: embeddings_reply(len(inputs))
    client.beta.conversations.start.return_value = SimpleNamespace(outputs=[])
    return client


def http_error(code):
    error = RuntimeError(f"HTTP {code}")
    error.status_code = code
    return error
