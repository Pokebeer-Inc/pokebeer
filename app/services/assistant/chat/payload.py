"""Lecture et validation de la requête du chat (JSON du navigateur) : un seul endroit, un seul type d'erreur."""
import json
from dataclasses import dataclass

from django.conf import settings

from .geo import Coordinates
from .sanitize import clean_text


class InvalidChatRequest(Exception):
    """Requête refusée ; le message est destiné au membre."""


@dataclass(frozen=True)
class ChatRequest:
    message: str
    location: Coordinates | None


def parse(body):
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise InvalidChatRequest("Format JSON invalide.")
    if not isinstance(data, dict):
        raise InvalidChatRequest("Format JSON invalide.")
    raw = data.get('message')
    if not isinstance(raw, str) or not clean_text(raw, 1):
        raise InvalidChatRequest("Message vide.")
    if len(raw) > settings.CHAT_MESSAGE_MAX_LENGTH:
        raise InvalidChatRequest(f"Message trop long ({settings.CHAT_MESSAGE_MAX_LENGTH} caractères maximum).")
    return ChatRequest(message=clean_text(raw, settings.CHAT_MESSAGE_MAX_LENGTH), location=Coordinates.parse(data.get('location')))
