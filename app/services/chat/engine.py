"""Dialogue avec Gemini : appel du modèle, exécution des outils demandés, réponse finale.

Le nombre de tours est borné (un modèle trompé ne peut pas boucler sur les outils), le dernier tour se fait sans outil pour forcer
une réponse, et chaque appel a un délai maximal.
"""
import logging

from django.conf import settings
from google.genai import types

from . import ChatUnavailable
from .sanitize import safe_reply

logger = logging.getLogger(__name__)

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


def converse(client, system_prompt, history, user_message, tools):
    """Réponse de Gaétan (texte déjà nettoyé). Lève ChatUnavailable si le modèle est injoignable."""
    contents = [types.Content(role=turn['role'], parts=[types.Part.from_text(text=turn['text'])]) for turn in history]
    contents.append(types.Content(role='user', parts=[types.Part.from_text(text=user_message)]))

    for round_number in range(MAX_TOOL_ROUNDS + 1):
        # Au dernier tour on retire les outils : le modèle doit répondre avec ce qu'il a
        config = _config(system_prompt, tools if round_number < MAX_TOOL_ROUNDS else None)
        try:
            response = client.models.generate_content(model=settings.CHAT_MODEL, contents=contents, config=config)
        except Exception as error:
            logger.warning("Gemini indisponible : %s", type(error).__name__)
            raise ChatUnavailable from error

        calls = (response.function_calls or []) if config.tools else []
        if not calls:
            return safe_reply(response.text or '') or BLOCKED_REPLY
        contents.append(response.candidates[0].content)
        contents.append(types.Content(role='user', parts=[
            # Chaque appel du modèle reçoit une réponse (l'API l'exige), mais seuls les premiers sont exécutés
            types.Part.from_function_response(name=call.name, response=_run_tool(tools, call, index < MAX_CALLS_PER_ROUND))
            for index, call in enumerate(calls)
        ]))
    return BLOCKED_REPLY  # inatteignable : le dernier tour n'a pas d'outil
