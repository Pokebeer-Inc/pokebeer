import logging

from google import genai
from google.genai import types
from django.conf import settings
from pgvector.django import CosineDistance
from ..models import Beer
from .chat import ChatUnavailable, engine, prompt, sanitize
from .chat.tools import build_tools

logger = logging.getLogger(__name__)

CONTEXT_SIZE = 10
# Appelé depuis des requêtes web (Beer.save) : on abandonne vite plutôt que de bloquer la fonction serverless
EMBEDDING_TIMEOUT_MS = 3000

# Initialisation du client avec la clé définie dans settings.py
def config_client():
    return genai.Client(api_key=settings.GEMINI_API_KEY)

def get_embedding(text):
    """Transforme un texte en vecteur mathématique (3072 dimensions, comme `Beer.embedding`) avec Gemini."""
    if not settings.GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY est introuvable.")
        return None
        
    try:
        client = config_client()
        response = client.models.embed_content(
            model='gemini-embedding-001',
            contents=text,
            config=types.EmbedContentConfig(http_options=types.HttpOptions(timeout=EMBEDDING_TIMEOUT_MS)),
        )
        return response.embeddings[0].values
        
    except Exception as e:
        logger.warning("Embedding Gemini en échec : %s", type(e).__name__)
        return None

def _select_beers(user_message, limit=CONTEXT_SIZE):
    """Recherche Vectorielle (Sémantique) avec pgvector, complétée par les bières pas encore vectorisées."""
    catalogue = Beer.objects.filter(is_deleted=False).select_related('brewery_id')
    user_vector = get_embedding(user_message)

    if not user_vector:
        # Fallback si l'API échoue
        return list(catalogue.order_by('?')[:limit])

    # Recherche les bières les plus proches sémantiquement
    beers = list(catalogue.exclude(embedding__isnull=True).order_by(CosineDistance('embedding', user_vector))[:limit])
    if len(beers) < limit:
        beers += catalogue.filter(embedding__isnull=True).order_by('?')[:limit - len(beers)]
    return beers

def _format_beers_context(user_message):
    beers = _select_beers(user_message)

    if not beers:
        return None

    # Noms et descriptions sont saisis par les membres : réduits à du texte brut court avant d'atteindre le modèle
    lines = []
    for b in beers:
        style = sanitize.clean_text(b.style, 60) or "Style inconnu"
        ibu_text = f"{b.bitterness} IBU" if b.bitterness is not None else "IBU inconnu"
        lines.append(
            f"- {sanitize.clean_text(b.name, 80)} ({sanitize.clean_text(b.brewery_id.name, 80)}): {style}, {b.degree}%, {ibu_text}. "
            f"Profil: {sanitize.clean_text(b.description, 200)}"
        )
    return "\n".join(lines)


def ask_zythologue(user_message, history=None, location=None):
    """Réponse de Gaétan. `location` (Coordinates ou None) sert aux questions de lieux et n'est ni transmise à Google ni conservée.

    Lève ChatUnavailable si le service ne peut pas répondre : l'appelant ne doit alors rien enregistrer.
    """
    if not settings.GEMINI_API_KEY:
        raise ChatUnavailable("Clé Gemini manquante")

    message = sanitize.clean_text(user_message, settings.CHAT_MESSAGE_MAX_LENGTH)
    turns = sanitize.clean_history(history, settings.CHAT_HISTORY_LIMIT, settings.CHAT_MESSAGE_MAX_LENGTH)
    system_prompt = prompt.build_system_prompt(_format_beers_context(message))
    try:
        client = config_client()
    except Exception as error:
        logger.warning("Client Gemini impossible à créer : %s", type(error).__name__)
        raise ChatUnavailable from error
    return engine.converse(client, system_prompt, turns, message, build_tools(location))
