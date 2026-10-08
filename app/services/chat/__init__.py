"""Assistant bière « Gaétan » : garde-fous, outils (lieux proches) et boucle de conversation avec Gemini.

Chaque module n'a qu'une responsabilité : `sanitize` (texte entrant et sortant), `geo` (position), `places` (sources de lieux),
`tools` (ce que le modèle peut appeler), `prompt` (consignes), `engine` (dialogue avec Gemini), `payload` (requête HTTP).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatReply:
    text: str
    needs_location: bool = False  # une recherche de lieux a échoué faute de position : le navigateur peut proposer de l'activer et de reprendre


class ChatUnavailable(Exception):
    """Le service ne peut pas répondre (clé absente, panne, réponse bloquée) : l'appelant rembourse le quota et n'enregistre rien."""


class ChatBusy(ChatUnavailable):
    """Le quota du modèle est atteint pour le moment (le nôtre ou celui de Gemini) : réessayer dans une minute suffit."""
