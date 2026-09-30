"""Assertions et raccourcis HTTP partagés par les tests de vues."""
import json

from django.contrib.messages import get_messages


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
