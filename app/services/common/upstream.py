"""Appel d'une API publique extérieure (Open Food Facts, annuaire des entreprises, communes) : un seul chemin, prudent.

L'adresse est toujours fixée par le code appelant (jamais par une saisie), aucune redirection n'est suivie, le délai et la taille de la
réponse sont bornés, et la réponse n'est jamais crue : elle doit être du JSON, le reste est nettoyé par l'appelant. Aucune donnée du membre
n'est transmise (la requête vient du serveur, sans cookie ni identifiant).
"""
import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 256 * 1024


class UpstreamUnavailable(Exception):
    """Le service ne répond pas correctement (panne, délai, réponse invalide) : à distinguer d'une réponse « introuvable »."""


def get_json(url, params=None, timeout=None):
    """Réponse JSON du service, ou None s'il répond 404 ; lève UpstreamUnavailable dans tous les autres cas d'échec."""
    try:
        response = requests.get(
            url, params=params, headers={'User-Agent': settings.UPSTREAM_USER_AGENT},
            timeout=timeout or settings.UPSTREAM_TIMEOUT, allow_redirects=False, stream=True,
        )
    except requests.RequestException as error:
        logger.warning("Service extérieur injoignable (%s) : %s", url.split('/')[2], type(error).__name__)
        raise UpstreamUnavailable from error
    with response:
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise UpstreamUnavailable(f"Statut {response.status_code}")
        try:
            body = response.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)
            if len(body) > MAX_RESPONSE_BYTES:
                raise UpstreamUnavailable("Réponse trop volumineuse")
            return json.loads(body)
        except (ValueError, requests.RequestException) as error:
            raise UpstreamUnavailable("Réponse illisible") from error
