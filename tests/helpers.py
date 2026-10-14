"""Assertions et raccourcis HTTP partagés par les tests de vues."""
import json

from django.contrib.messages import get_messages

from app.models import ThrottleHit
from app.services.protection import throttle


def post_json(client, url, payload=None, raw=None):
    body = raw if raw is not None else json.dumps(payload or {})
    return client.post(url, data=body, content_type="application/json")


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def assert_redirects_to_login(response):
    assert response.status_code == 302
    assert "login" in response.url


def assert_redirects(response, expected_url):
    assert response.status_code == 302
    assert response.url == expected_url


def exhaust(rule, key, remaining=0):
    """Consomme d'avance les tentatives de `rule` pour `key`, en n'en laissant que `remaining` : teste un plafond sans l'atteindre requête par requête."""
    ThrottleHit.objects.bulk_create([ThrottleHit(scope=rule.scope, key_hash=throttle._digest(key)) for _ in range(rule.attempts - remaining)])
