"""Dialogue avec Gemini : appel du modèle, exécution des outils demandés, réponse finale.

Le nombre de tours est borné (un modèle trompé ne peut pas boucler sur les outils), le dernier tour se fait sans outil pour forcer
une réponse, et chaque appel a un délai maximal.
"""
import logging

from django.conf import settings
from django.core.cache import cache
from google.genai import types

from . import ChatBusy, ChatReply, ChatUnavailable
from .tools import NEEDS_LOCATION_KEY
from .sanitize import safe_reply

logger = logging.getLogger(__name__)

RATE_LIMITED = 429
# Erreurs où un autre modèle peut réussir : quota atteint, modèle retiré, service surchargé
COOLDOWN_SECONDS = 60  # un modèle qui vient de refuser faute de quota est laissé de côté ce temps-là
FALLBACK_CODES = frozenset({RATE_LIMITED, 404, 500, 502, 503, 504})

MAX_TOOL_ROUNDS = 2
MAX_CALLS_PER_ROUND = 2
TOO_MANY_CALLS = {'error': "Trop d'appels à la fois : réponds avec les résultats déjà obtenus."}
BLOCKED_REPLY = "Je préfère ne pas répondre à cela. Parlons plutôt bière : qu'avez-vous envie de goûter ?"
TOOL_FAILED = {'error': "L'outil a échoué : réponds sans lui et préviens le membre que les lieux n'ont pas pu être consultés."}
_BLOCKED_CATEGORIES = (
    types.HarmCategory.HARM_CATEGORY_HARASSMENT, types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
    types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
)


def _config(system_prompt, tools):
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.4,
        max_output_tokens=settings.CHAT_MAX_OUTPUT_TOKENS,
        http_options=types.HttpOptions(timeout=settings.CHAT_GENERATION_TIMEOUT_MS),
        # Pas de « réflexion » facturée sur le quota pour une conversation simple ; outils appelés par nous, jamais automatiquement
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        safety_settings=[types.SafetySetting(category=c, threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE) for c in _BLOCKED_CATEGORIES],
        tools=[types.Tool(function_declarations=[tool.declaration() for tool in tools.values()])] if tools else None,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


def _cooldown_key(model):
    return f'chat-model-cooldown:{model}'


def _generate(client, contents, config):
    """Appel au premier modèle disponible de CHAT_MODELS. Chaque modèle a son quota gratuit : le suivant prend le relais s'il est saturé."""
    saturated = False
    for model in settings.CHAT_MODELS:
        if cache.get(_cooldown_key(model)):
            saturated = True
            continue
        try:
            return client.models.generate_content(model=model, contents=contents, config=config)
        except Exception as error:
            code = getattr(error, 'code', None)
            logger.warning("Gemini (%s) indisponible : %s %s", model, type(error).__name__, code)
            if code == RATE_LIMITED:
                saturated = True
                cache.set(_cooldown_key(model), True, COOLDOWN_SECONDS)
            if code not in FALLBACK_CODES:
                raise ChatUnavailable from error
    raise ChatBusy if saturated else ChatUnavailable


def _run_tool(tools, call, allowed):
    if not allowed:
        return TOO_MANY_CALLS
    tool = tools.get(call.name)
    if tool is None:
        return {'error': 'Outil inconnu.'}
    try:
        return tool.run(dict(call.args or {}))
    except Exception as error:  # un outil en panne ne doit jamais faire tomber la conversation
        logger.warning("Outil %s en échec : %s", call.name, type(error).__name__)
        return TOOL_FAILED


def converse(client, system_prompt, history, user_message, tools, reserve_call=lambda: None):
    """Réponse de Gaétan (ChatReply, texte déjà nettoyé). Lève ChatUnavailable si le modèle est injoignable, ChatBusy si son quota est atteint.

    `reserve_call` est appelée avant chaque appel au modèle (une réponse avec outil en demande deux) et peut lever ChatBusy."""
    contents = [types.Content(role=turn['role'], parts=[types.Part.from_text(text=turn['text'])]) for turn in history]
    contents.append(types.Content(role='user', parts=[types.Part.from_text(text=user_message)]))

    needs_location = False
    for round_number in range(MAX_TOOL_ROUNDS + 1):
        # Au dernier tour on retire les outils : le modèle doit répondre avec ce qu'il a
        config = _config(system_prompt, tools if round_number < MAX_TOOL_ROUNDS else None)
        reserve_call()
        response = _generate(client, contents, config)

        calls = (response.function_calls or []) if config.tools else []
        if not calls:
            return ChatReply(safe_reply(response.text or '') or BLOCKED_REPLY, needs_location)
        contents.append(response.candidates[0].content)
        results = [_run_tool(tools, call, index < MAX_CALLS_PER_ROUND) for index, call in enumerate(calls)]
        needs_location = needs_location or any(result.get(NEEDS_LOCATION_KEY) for result in results)
        # Chaque appel du modèle reçoit une réponse (l'API l'exige), mais seuls les premiers sont exécutés
        contents.append(types.Content(role='user', parts=[
            types.Part.from_function_response(name=call.name, response=result) for call, result in zip(calls, results)
        ]))
    return ChatReply(BLOCKED_REPLY)  # inatteignable : le dernier tour n'a pas d'outil
