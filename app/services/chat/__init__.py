"""Assistant bière « Gaétan » : garde-fous, outils (lieux proches) et boucle de conversation avec Gemini.

Chaque module n'a qu'une responsabilité : `sanitize` (texte entrant et sortant), `geo` (position), `places` (sources de lieux),
`tools` (ce que le modèle peut appeler), `prompt` (consignes), `engine` (dialogue avec Gemini), `payload` (requête HTTP).
"""


class ChatUnavailable(Exception):
    """Le service ne peut pas répondre (clé absente, panne, réponse bloquée) : l'appelant rembourse le quota et n'enregistre rien."""
