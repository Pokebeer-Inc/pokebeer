"""Accès à Mistral AI (hébergé dans l'Union européenne) : client, budget d'appels par minute et embeddings.

Un seul endroit parle au fournisseur : le dialogue (`chat/engine`), l'analyse d'étiquette (`label_scan`) et les embeddings passent
ici, remplacer le fournisseur ne touche donc que ce module et ceux qui construisent les messages.
"""
import logging

from django.conf import settings
from mistralai.client import Mistral

from .throttle import CHAT_MODEL_CALLS

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32


def get_client(timeout_ms=None):
    """Client Mistral. Aucune donnée n'est conservée par le SDK ; le délai borne chaque appel (fonction serverless)."""
    return Mistral(api_key=settings.MISTRAL_API_KEY, timeout_ms=timeout_ms or settings.LLM_TIMEOUT_MS)


def status_code(error):
    """Code HTTP d'une erreur du SDK (None pour une panne réseau ou une erreur locale)."""
    return getattr(error, 'status_code', None)


def text_of(content):
    """Texte d'une réponse (chaîne, ou liste de morceaux pour certains modèles) ; les références et autres morceaux sont ignorés."""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return ''.join(chunk.text for chunk in content if isinstance(getattr(chunk, 'text', None), str))
    return ''


def conversation_text(response):
    """Dernière réponse écrite d'une conversation (API Conversations : l'outil de recherche web n'existe pas en chat simple)."""
    for entry in reversed(getattr(response, 'outputs', None) or []):
        text = text_of(getattr(entry, 'content', None))
        if text:
            return text
    return ''


def conversation_sources(response):
    """Adresses https citées par la recherche web (références des morceaux de la réponse) : sans elles, rien n'est confirmé."""
    urls = []
    for entry in getattr(response, 'outputs', None) or []:
        content = getattr(entry, 'content', None)
        for chunk in content if isinstance(content, (list, tuple)) else ():
            url = getattr(chunk, 'url', None)
            if getattr(chunk, 'type', None) == 'tool_reference' and isinstance(url, str) and url.startswith('https://'):
                urls.append(url)
    return urls


def reserve_call(model):
    """Réserve un appel dans le budget par minute de ce modèle (chaque modèle a ses propres limites) ; False s'il est dépensé."""
    if CHAT_MODEL_CALLS.exceeded(model):
        return False
    CHAT_MODEL_CALLS.record(model)
    return True


def embed(texts, budgeted=True):
    """Vecteurs des textes (même ordre), ou None si le service est indisponible, le budget dépensé ou la réponse inattendue.

    `budgeted=False` pour les traitements par lots (commande d'administration) qui gèrent eux-mêmes leur rythme."""
    texts = list(texts)
    if not texts:
        return []
    if not settings.MISTRAL_API_KEY:
        logger.error("MISTRAL_API_KEY est introuvable.")
        return None
    vectors = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start:start + EMBED_BATCH_SIZE]
        if budgeted and not reserve_call(settings.MISTRAL_EMBED_MODEL):
            return None
        try:
            response = get_client(settings.EMBEDDING_TIMEOUT_MS).embeddings.create(model=settings.MISTRAL_EMBED_MODEL, inputs=batch)
            batch_vectors = [list(item.embedding) for item in response.data]
        except Exception as error:
            logger.warning("Embedding Mistral en échec : %s %s", type(error).__name__, status_code(error))
            return None
        # Une réponse qui ne correspond pas à la colonne (nombre ou taille) ne doit jamais atteindre la base
        if len(batch_vectors) != len(batch) or any(len(vector) != settings.EMBEDDING_DIMENSIONS for vector in batch_vectors):
            logger.error("Embedding Mistral inattendu : %s vecteurs, dimensions %s", len(batch_vectors), {len(v) for v in batch_vectors})
            return None
        vectors.extend(batch_vectors)
    return vectors
