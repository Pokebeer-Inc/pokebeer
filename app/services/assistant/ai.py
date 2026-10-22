import logging
import random

from django.conf import settings
from django.db.models import Max, Min
from pgvector.django import CosineDistance
from ...models import Beer
from ..members.visibility import exclude_blocked
from ..catalog import label_scan
from . import llm
from .chat import ChatUnavailable, engine, prompt, sanitize
from .chat.tools import build_tools

logger = logging.getLogger(__name__)

CONTEXT_SIZE = 10


def get_embedding(text):
    """Transforme un texte en vecteur (`settings.EMBEDDING_DIMENSIONS` dimensions, comme `Beer.embedding`) avec Mistral ; None en cas d'échec."""
    vectors = llm.embed([text])
    return vectors[0] if vectors else None


def _random_sample(queryset, limit):
    """`limit` lignes au hasard sans trier toute la table (`ORDER BY RANDOM()` lit et trie chaque ligne).

    Tire des clés au hasard dans l'intervalle des identifiants, puis complète dans l'ordre s'il y a trop de trous."""
    bounds = queryset.aggregate(low=Min('pk'), high=Max('pk'))
    if bounds['low'] is None:
        return []
    span = bounds['high'] - bounds['low'] + 1
    picks = random.sample(range(bounds['low'], bounds['high'] + 1), min(span, limit * 4))
    rows = list(queryset.filter(pk__in=picks)[:limit])
    if len(rows) < limit:
        rows += list(queryset.exclude(pk__in=[row.pk for row in rows])[:limit - len(rows)])
    random.shuffle(rows)
    return rows


def _select_beers(user_message, limit=CONTEXT_SIZE, user=None):
    """Recherche Vectorielle (Sémantique) avec pgvector, complétée par les bières pas encore vectorisées.

    Les bières ajoutées par un membre qui a un blocage avec `user` ne sont jamais proposées."""
    catalogue = Beer.objects.filter(is_deleted=False).select_related('brewery')
    if user is not None:
        catalogue = exclude_blocked(catalogue, user, 'added_by')
    user_vector = get_embedding(user_message)

    if not user_vector:
        # Fallback si l'API échoue
        return _random_sample(catalogue, limit)

    # Recherche les bières les plus proches sémantiquement
    beers = list(catalogue.exclude(embedding__isnull=True).order_by(CosineDistance('embedding', user_vector))[:limit])
    if len(beers) < limit:
        beers += _random_sample(catalogue.filter(embedding__isnull=True), limit - len(beers))
    return beers

def _format_beers_context(user_message, user=None):
    beers = _select_beers(user_message, user=user)

    if not beers:
        return None

    # Noms et descriptions sont saisis par les membres : réduits à du texte brut court avant d'atteindre le modèle
    lines = []
    for b in beers:
        style = sanitize.clean_text(b.style, 60) or "Style inconnu"
        ibu_text = f"{b.bitterness} IBU" if b.bitterness is not None else "IBU inconnu"
        lines.append(
            f"- {sanitize.clean_text(b.name, 80)} ({sanitize.clean_text(b.brewery_label, 80)}): {style}, {b.degree}%, {ibu_text}. "
            f"Profil: {sanitize.clean_text(b.description, 200)}"
        )
    return "\n".join(lines)


def ask_zythologue(user_message, history=None, location=None, user=None):
    """Réponse de Gaétan. `location` (Coordinates ou None) sert aux questions de lieux et n'est ni transmise à Google ni conservée.

    Lève ChatUnavailable si le service ne peut pas répondre : l'appelant ne doit alors rien enregistrer.
    """
    if not settings.MISTRAL_API_KEY:
        raise ChatUnavailable("Clé Mistral manquante")

    message = sanitize.clean_text(user_message, settings.CHAT_MESSAGE_MAX_LENGTH)
    turns = sanitize.clean_history(history, settings.CHAT_HISTORY_LIMIT, settings.CHAT_MESSAGE_MAX_LENGTH)
    system_prompt = prompt.build_system_prompt(_format_beers_context(message, user=user))
    try:
        client = llm.get_client()
    except Exception as error:
        logger.warning("Client Mistral impossible à créer : %s", type(error).__name__)
        raise ChatUnavailable from error
    return engine.converse(client, system_prompt, turns, message, build_tools(location), llm.reserve_call)


def analyze_label(image_bytes):
    """Bière lue sur l'étiquette (label_scan.Reading : {name, brewery, style, degree, bitterness} et l'origine de ce qui n'était pas imprimé), ou None.

    Lève ValueError si la réponse du modèle est inutilisable et toute autre exception si le service est en panne : l'appelant rembourse alors l'essai."""
    return label_scan.analyze(llm.get_client(settings.LABEL_TIMEOUT_MS), image_bytes, llm.reserve_call)
