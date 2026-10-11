"""Dialogue avec Mistral : appel du modèle, exécution des outils demandés, réponse finale.

Le nombre de tours est borné (un modèle trompé ne peut pas boucler sur les outils), le dernier tour se fait sans outil pour forcer
une réponse, et chaque appel a un délai maximal.
"""
import json
import logging

from django.conf import settings
from django.core.cache import cache

from .. import llm
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
NEEDS_LOCATION_REPLY = "Pour chercher près de vous, j'ai besoin de votre position : activez-la ci-dessous, ou citez une ville dans votre question."
BLOCKED_REPLY = "Je préfère ne pas répondre à cela. Parlons plutôt bière : qu'avez-vous envie de goûter ?"
TOOL_FAILED = {'error': "L'outil a échoué : réponds sans lui et préviens le membre que les lieux n'ont pas pu être consultés."}
API_ROLES = {'user': 'user', 'model': 'assistant'}  # l'historique garde « model » ; l'API attend « assistant »


def _cooldown_key(model):
    return f'chat-model-cooldown:{model}'


def _generate(client, messages, tool_specs, reserve_call):
    """Appel au premier modèle disponible de CHAT_MODELS. Chaque modèle a son quota gratuit : le suivant prend le relais s'il est saturé,
    qu'il l'ait signalé (429) ou que son budget par minute soit déjà dépensé (`reserve_call(model)` renvoie False)."""
    options = {'temperature': 0.4, 'max_tokens': settings.CHAT_MAX_OUTPUT_TOKENS, 'timeout_ms': settings.CHAT_GENERATION_TIMEOUT_MS, 'safe_prompt': True}
    if tool_specs:  # outils appelés par nous, jamais automatiquement
        options.update(tools=tool_specs, tool_choice='auto')
    saturated = False
    for model in settings.CHAT_MODELS:
        if cache.get(_cooldown_key(model)) or not reserve_call(model):
            saturated = True
            continue
        try:
            return client.chat.complete(model=model, messages=messages, **options).choices[0].message
        except Exception as error:
            code = llm.status_code(error)
            logger.warning("Mistral (%s) indisponible : %s %s", model, type(error).__name__, code)
            if code == RATE_LIMITED:
                saturated = True
                cache.set(_cooldown_key(model), True, COOLDOWN_SECONDS)
            if code not in FALLBACK_CODES:
                raise ChatUnavailable from error
    raise ChatBusy if saturated else ChatUnavailable


def _tool_calls(message):
    calls = getattr(message, 'tool_calls', None)
    return list(calls) if isinstance(calls, (list, tuple)) else []


def _arguments(call):
    """Arguments d'un appel d'outil : un dict, jamais autre chose (la sortie d'un modèle est une entrée non fiable)."""
    raw = call.function.arguments
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _run_tool(tools, call, allowed):
    if not allowed:
        return TOO_MANY_CALLS
    tool = tools.get(call.function.name)
    if tool is None:
        return {'error': 'Outil inconnu.'}
    try:
        return tool.run(_arguments(call))
    except Exception as error:  # un outil en panne ne doit jamais faire tomber la conversation
        logger.warning("Outil %s en échec : %s", call.function.name, type(error).__name__)
        return TOOL_FAILED


def converse(client, system_prompt, history, user_message, tools, reserve_call=lambda model: True):
    """Réponse de Gaétan (ChatReply, texte déjà nettoyé). Lève ChatUnavailable si le modèle est injoignable, ChatBusy si son quota est atteint.

    `reserve_call(model)` est appelée avant chaque appel à un modèle (une réponse avec outil en demande deux) : elle renvoie False quand le
    budget de ce modèle est dépensé, et le suivant est alors essayé."""
    messages = [{'role': 'system', 'content': system_prompt}]
    messages += [{'role': API_ROLES[turn['role']], 'content': turn['text']} for turn in history]
    messages.append({'role': 'user', 'content': user_message})
    tool_specs = [tool.declaration() for tool in tools.values()]

    for round_number in range(MAX_TOOL_ROUNDS + 1):
        # Au dernier tour on retire les outils : le modèle doit répondre avec ce qu'il a
        offered = tool_specs if round_number < MAX_TOOL_ROUNDS else None
        message = _generate(client, messages, offered, reserve_call)

        calls = _tool_calls(message) if offered else []
        if not calls:
            return ChatReply(safe_reply(llm.text_of(message.content)) or BLOCKED_REPLY)
        messages.append({'role': 'assistant', 'content': llm.text_of(message.content), 'tool_calls': [
            {'id': call.id, 'type': 'function', 'function': {'name': call.function.name, 'arguments': json.dumps(_arguments(call))}} for call in calls
        ]})
        results = [_run_tool(tools, call, index < MAX_CALLS_PER_ROUND) for index, call in enumerate(calls)]
        if all(result.get(NEEDS_LOCATION_KEY) for result in results):
            # Rien à dire de plus au modèle : le navigateur obtient la position et renvoie la même demande (un appel au modèle économisé)
            return ChatReply(NEEDS_LOCATION_REPLY, needs_location=True)
        # Chaque appel du modèle reçoit une réponse (l'API l'exige), mais seuls les premiers sont exécutés
        messages += [
            {'role': 'tool', 'tool_call_id': call.id, 'name': call.function.name, 'content': json.dumps(result, ensure_ascii=False)}
            for call, result in zip(calls, results)
        ]
    return ChatReply(BLOCKED_REPLY)  # inatteignable : le dernier tour n'a pas d'outil
