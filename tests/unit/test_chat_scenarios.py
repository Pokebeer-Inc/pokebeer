"""Scénarios de bout en bout de Gaétan : moteur réel, outil réel, Gemini et sources de lieux factices.

Ils couvrent la position (connue, absente, ville nommée), l'enchaînement des outils, le budget d'appels par modèle et la reprise
d'une demande après activation de la position.
"""
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import pytest
from django.core.cache import cache
from django.urls import reverse

from app.models import QuotaUsage
from app.services.assistant import ai, llm
from app.services.assistant.chat import ChatBusy, ChatReply, ChatUnavailable, engine, geocoding, places
from app.services.assistant.chat.geo import Coordinates
from app.services.assistant.chat.tools import build_tools
from app.services.protection.throttle import Rule
from tests.fakes import chat_reply, tool_call, tool_reply
from tests.helpers import post_json

pytestmark = pytest.mark.django_db

LILLE = Coordinates(50.63, 3.06)
PLACE = places.Place(name="Le Comptoir", kind="bar", distance_km=0.8, address="1 rue du Port", link="/bar/le-comptoir/", source="pokebeer", verified=True)


def text(value):
    return chat_reply(value)


def call(**args):
    return tool_call(arguments=json.dumps(args))


def tools_round(*calls):
    return tool_reply(*calls)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    cache.clear()
    monkeypatch.setattr(places, "find_nearby", mock.Mock(return_value=places.NearbyResult([PLACE], True)))
    monkeypatch.setattr(geocoding, "geocode", mock.Mock(return_value=LILLE))


@pytest.fixture
def client():
    client = mock.Mock()
    return client


def converse(client, message, origin=None, history=(), reserve=lambda model: True):
    return engine.converse(client, "système", list(history), message, build_tools(origin), reserve)


class TestWithAKnownPosition:
    def test_a_places_question_is_answered_with_the_tool_result(self, client):
        client.chat.complete.side_effect = [tools_round(call(kind="bar")), text("Le Comptoir, à 0,8 km")]
        reply = converse(client, "Un bar près de moi ?", origin=LILLE)
        assert reply.text == "Le Comptoir, à 0,8 km" and reply.needs_location is False
        assert places.find_nearby.call_args.args[0] == LILLE

    def test_the_position_is_never_part_of_what_the_model_receives(self, client):
        client.chat.complete.side_effect = [tools_round(call(kind="bar")), text("ok")]
        converse(client, "Un bar près de moi ?", origin=LILLE)
        sent = repr([c.kwargs["messages"] for c in client.chat.complete.call_args_list])
        assert "50.63" not in sent and "3.06" not in sent

    def test_two_kinds_of_places_can_be_searched_in_one_round(self, client):
        client.chat.complete.side_effect = [tools_round(call(kind="bar"), call(kind="brewery")), text("Voici les deux")]
        converse(client, "Bars et brasseries près de moi ?", origin=LILLE)
        assert places.find_nearby.call_count == 2 and client.chat.complete.call_count == 2


class TestWithoutPosition:
    def test_the_browser_is_told_to_ask_for_the_position_with_a_single_model_call(self, client):
        client.chat.complete.side_effect = [tools_round(call(kind="bar")), text("jamais lu")]
        reply = converse(client, "Un bar près de moi ?")
        assert reply.needs_location is True and reply.text == engine.NEEDS_LOCATION_REPLY
        assert client.chat.complete.call_count == 1
        places.find_nearby.assert_not_called()

    def test_a_named_city_needs_no_position(self, client):
        client.chat.complete.side_effect = [tools_round(call(kind="bar", place_name="Lille")), text("À Lille")]
        reply = converse(client, "Un bar à Lille ?")
        assert reply.needs_location is False and places.find_nearby.call_args.args[0] == LILLE

    def test_an_unknown_city_does_not_ask_for_the_position(self, client, monkeypatch):
        monkeypatch.setattr(geocoding, "geocode", mock.Mock(return_value=None))
        client.chat.complete.side_effect = [tools_round(call(kind="bar", place_name="Zzzz")), text("Ville introuvable")]
        assert converse(client, "Un bar à Zzzz ?").needs_location is False

    def test_a_city_wins_over_the_device_position(self, client):
        client.chat.complete.side_effect = [tools_round(call(place_name="Lille")), text("ok")]
        converse(client, "Un bar à Lille ?", origin=Coordinates(48.85, 2.35))
        assert places.find_nearby.call_args.args[0] == LILLE


class TestChainingTasks:
    def test_the_last_round_has_no_tools_so_a_model_that_insists_gets_the_fallback_reply(self, client):
        client.chat.complete.side_effect = [tools_round(call()), tools_round(call()), tools_round(call())]
        reply = converse(client, "Enchaîne", origin=LILLE)
        assert places.find_nearby.call_count == engine.MAX_TOOL_ROUNDS
        assert reply.text == engine.BLOCKED_REPLY  # réponse de « refus » alors que rien n'a été refusé : à revoir

    def test_a_tool_failure_is_reported_to_the_model_not_raised(self, client):
        places.find_nearby.side_effect = RuntimeError("boom")
        client.chat.complete.side_effect = [tools_round(call()), text("Je n'ai pas pu consulter les lieux")]
        assert "pas pu" in converse(client, "Un bar ?", origin=LILLE).text


class TestBudgetPerModel:
    """Chaque réponse avec outil coûte deux appels au modèle ; le budget par minute est compté modèle par modèle."""

    def test_a_places_answer_costs_two_model_calls(self, client):
        reserve = mock.Mock(return_value=True)
        client.chat.complete.side_effect = [tools_round(call()), text("ok")]
        converse(client, "Un bar ?", origin=LILLE, reserve=reserve)
        assert reserve.call_count == 2

    def test_three_places_answers_in_a_minute_are_served_by_the_models_in_turn(self, client, settings, monkeypatch):
        monkeypatch.setattr(llm, "CHAT_MODEL_CALLS", Rule("chat-model-calls", 4, timedelta(minutes=1)))
        for _ in range(3):
            client.chat.complete.side_effect = [tools_round(call()), text("ok")]
            converse(client, "Un bar ?", origin=LILLE, reserve=llm.reserve_call)
        used = {c.kwargs["model"] for c in client.chat.complete.call_args_list}
        assert len(used) > 1 and all(model in settings.CHAT_MODELS for model in used)

    def test_busy_only_when_every_model_has_spent_its_budget(self, client, settings):
        client.chat.complete.return_value = text("ok")
        budget = settings.CHAT_MODEL_CALLS_PER_MINUTE * len(settings.CHAT_MODELS)
        for _ in range(budget):
            converse(client, "Salut", reserve=llm.reserve_call)
        with pytest.raises(ChatBusy):
            converse(client, "Salut", reserve=llm.reserve_call)


class TestResumeAfterEnablingThePosition:
    @pytest.fixture
    def chat(self, auth_client, monkeypatch):
        monkeypatch.setattr("app.views.api_views.CHAT_BURST_BY_USER", Rule("chat-burst", 10_000, timedelta(minutes=1)))
        asked = mock.Mock(side_effect=lambda message, history, location=None, user=None: ChatReply("Activez votre position", True) if location is None else ChatReply("Le Comptoir"))
        monkeypatch.setattr("app.views.api_views.ask_zythologue", asked)
        return SimpleNamespace(client=auth_client, asked=asked)

    def test_the_resent_message_carries_the_position(self, chat):
        url = reverse("chat_api")
        assert post_json(chat.client, url, {"message": "Une IPA près de moi ?"}).json()["needs_location"] is True
        post_json(chat.client, url, {"message": "Une IPA près de moi ?", "location": {"lat": 50.63, "lng": 3.06}})
        assert chat.asked.call_args.args[0] == "Une IPA près de moi ?" and chat.asked.call_args.args[2] == LILLE

    def test_resuming_does_not_spend_a_second_daily_message(self, chat, user):
        url = reverse("chat_api")
        post_json(chat.client, url, {"message": "Une IPA près de moi ?"})
        post_json(chat.client, url, {"message": "Une IPA près de moi ?", "location": {"lat": 50.63, "lng": 3.06}})
        assert QuotaUsage.objects.get(user=user).count == 1

    def test_the_browser_cannot_claim_a_resume_to_skip_the_quota(self, chat, user):
        url = reverse("chat_api")
        for _ in range(2):  # sans demande en attente côté serveur, même avec position, chaque message compte
            post_json(chat.client, url, {"message": "Une IPA près de moi ?", "location": {"lat": 50.63, "lng": 3.06}})
        assert QuotaUsage.objects.get(user=user).count == 2

    def test_a_resume_is_valid_for_the_pending_message_only(self, chat, user):
        url = reverse("chat_api")
        post_json(chat.client, url, {"message": "Une IPA près de moi ?"})
        post_json(chat.client, url, {"message": "Autre chose", "location": {"lat": 50.63, "lng": 3.06}})
        assert QuotaUsage.objects.get(user=user).count == 2

    def test_the_unanswered_request_is_not_kept_in_the_history(self, chat):
        url = reverse("chat_api")
        post_json(chat.client, url, {"message": "Une IPA près de moi ?"})
        assert chat.client.get(url).json()["history"] == []
        post_json(chat.client, url, {"message": "Une IPA près de moi ?", "location": {"lat": 50.63, "lng": 3.06}})
        assert [turn["text"] for turn in chat.client.get(url).json()["history"]] == ["Une IPA près de moi ?", "Le Comptoir"]

    def test_a_resume_that_fails_can_be_tried_again_for_free(self, auth_client, user, monkeypatch):
        monkeypatch.setattr("app.views.api_views.CHAT_BURST_BY_USER", Rule("chat-burst", 10_000, timedelta(minutes=1)))
        answers = [ChatReply("Position ?", True), ChatUnavailable(), ChatReply("Le Comptoir")]
        monkeypatch.setattr("app.views.api_views.ask_zythologue", mock.Mock(side_effect=answers))
        url, body = reverse("chat_api"), {"message": "Un bar ?", "location": {"lat": 50.63, "lng": 3.06}}
        post_json(auth_client, url, {"message": "Un bar ?"})
        assert post_json(auth_client, url, body).status_code == 503
        assert post_json(auth_client, url, body).status_code == 200
        assert QuotaUsage.objects.get(user=user).count == 1

    def test_the_catalogue_is_searched_with_the_original_request_when_resuming(self, client, monkeypatch, settings):
        monkeypatch.setattr(llm, "get_client", lambda *args, **kwargs: client)
        client.chat.complete.return_value = text("ok")
        seen = mock.Mock(return_value="")
        monkeypatch.setattr(ai, "_format_beers_context", seen)
        ai.ask_zythologue("Une IPA près de moi ?", [], LILLE)
        assert "IPA" in seen.call_args.args[0]
