"""Tout texte qui entre dans le modèle ou en sort passe ici.

Entrée : les noms, descriptions et adresses viennent des membres ou d'OpenStreetMap, donc d'inconnus. Ils sont réduits à du texte
brut court avant d'être montrés au modèle (injection indirecte de consignes).
Sortie : le modèle peut être trompé ; on ne laisse passer ni image distante (fuite de la conversation via l'URL), ni HTML, ni lien
vers un hôte non prévu (hameçonnage).
"""
import re
import unicodedata
from urllib.parse import urlparse

ALLOWED_LINK_HOSTS = frozenset({'www.openstreetmap.org', 'openstreetmap.org'})
ROLES = frozenset({'user', 'model'})

# Caractères de contrôle, de largeur nulle et de sens d'écriture : invisibles pour le membre, utilisés pour cacher des consignes
_INVISIBLE = re.compile('[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁠-⁤⁦-⁩﻿]')
_SPACES = re.compile(r'\s+')
_MARKUP = re.compile(r'[<>`]')
_HTML_TAG = re.compile(r'</?[a-zA-Z!][^>]*>?')
# Une seule passe : image, lien [texte](adresse) ou adresse nue (essayés dans cet ordre à chaque position)
_URLS = re.compile(r'!\[[^\]]*\]\([^)]*\)|\[([^\]]*)\]\(\s*([^)\s]*)[^)]*\)|https?://[^\s<>()\[\]]+', re.IGNORECASE)


def clean_text(value, limit):
    """Texte brut sur une ligne, sans caractère invisible ni balise, tronqué à `limit` caractères."""
    if not isinstance(value, str):
        return ''
    text = unicodedata.normalize('NFKC', value)
    text = _MARKUP.sub(' ', _INVISIBLE.sub('', text))
    return _SPACES.sub(' ', text).strip()[:limit]


def clean_history(history, max_messages, max_length):
    """Historique de session réduit aux tours valides (rôle connu, texte non vide) : jamais un rôle ou un type inattendu vers le modèle."""
    turns = []
    for message in history if isinstance(history, list) else []:
        if isinstance(message, dict) and message.get('role') in ROLES:
            text = clean_text(message.get('text'), max_length)
            if text:
                turns.append({'role': message['role'], 'text': text})
    return turns[-max_messages:]


def _link_is_allowed(url):
    if url.startswith('/') and not url.startswith('//') and '\\' not in url:
        return True
    parsed = urlparse(url)
    return parsed.scheme == 'https' and parsed.hostname in ALLOWED_LINK_HOSTS


def _filter_url(match):
    if match.group(0).startswith('!') or match.group(2) is None:
        return ''  # image distante ou adresse nue
    return match.group(0) if _link_is_allowed(match.group(2)) else match.group(1)


def safe_reply(text):
    """Réponse du modèle débarrassée de tout ce qui pourrait sortir de la page : images, HTML, liens non autorisés."""
    return _URLS.sub(_filter_url, _HTML_TAG.sub('', text)).strip()
