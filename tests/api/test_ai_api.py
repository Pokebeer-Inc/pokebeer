from types import SimpleNamespace
from unittest import mock

import pytest
from django.urls import reverse

from tests import factories as f
from tests.helpers import post_json

pytestmark = pytest.mark.django_db

CHAT_URL = reverse("chat_api")
LABEL_URL = reverse("analyze_label")
HISTORY_LIMIT = 10


@pytest.fixture
def zythologue(monkeypatch):
    ask = mock.Mock(side_effect=lambda message, history: f"Réponse à {message}")
    monkeypatch.setattr("app.views.api_views.ask_zythologue", ask)
    return ask


@pytest.fixture
def label_client(monkeypatch):
    client = mock.Mock()
    monkeypatch.setattr("app.views.api_views.config_client", lambda: client)
    return client


class TestChat:
    def test_history_is_empty_at_first(self, auth_client):
        assert auth_client.get(CHAT_URL).json() == {"history": []}

    def test_exchange_is_answered_and_stored_in_session(self, auth_client, zythologue):
        assert post_json(auth_client, CHAT_URL, {"message": "Une stout ?"}).json() == {"response": "Réponse à Une stout ?"}
        assert auth_client.get(CHAT_URL).json()["history"] == [
            {"role": "user", "text": "Une stout ?"}, {"role": "model", "text": "Réponse à Une stout ?"},
        ]

    def test_history_is_capped(self, auth_client, zythologue):
        for i in range(HISTORY_LIMIT):
            post_json(auth_client, CHAT_URL, {"message": f"m{i}"})
        history = auth_client.get(CHAT_URL).json()["history"]
        assert len(history) == HISTORY_LIMIT
        assert history[0]["text"] == "m5"

    def test_history_is_private_to_the_session(self, auth_client, other_client, zythologue):
        post_json(auth_client, CHAT_URL, {"message": "secret"})
        assert other_client.get(CHAT_URL).json() == {"history": []}

    @pytest.mark.parametrize("payload, raw", [
        ({"message": "   "}, None), ({}, None), ({"message": 42}, None), ({"message": ["a"]}, None),
        (None, "not-json"), (None, "[1, 2]"),
    ])
    def test_invalid_messages_are_rejected_without_calling_ai(self, auth_client, zythologue, payload, raw):
        assert post_json(auth_client, CHAT_URL, payload, raw=raw).status_code == 400
        zythologue.assert_not_called()

    def test_ai_outage_still_answers(self, auth_client):
        assert post_json(auth_client, CHAT_URL, {"message": "Bonjour"}).json()["response"].startswith("Désolé")

    def test_anonymous_cannot_use_the_paid_ai(self, client, zythologue):
        assert post_json(client, CHAT_URL, {"message": "Bonjour"}).status_code == 302
        zythologue.assert_not_called()

    @pytest.mark.parametrize("method", ["put", "delete", "patch"])
    def test_other_http_methods_are_refused(self, auth_client, method):
        assert getattr(auth_client, method)(CHAT_URL).status_code == 405

    def test_message_of_max_length_is_accepted(self, auth_client, zythologue, settings):
        assert post_json(auth_client, CHAT_URL, {"message": "x" * settings.CHAT_MESSAGE_MAX_LENGTH}).status_code == 200

    def test_oversized_message_is_rejected_without_using_quota(self, auth_client, zythologue, settings, user):
        assert post_json(auth_client, CHAT_URL, {"message": "x" * (settings.CHAT_MESSAGE_MAX_LENGTH + 1)}).status_code == 400
        zythologue.assert_not_called()
        assert not user.chat_usages.exists()


class TestChatQuota:
    LIMIT = 3

    @pytest.fixture(autouse=True)
    def small_limit(self, settings):
        settings.CHAT_DAILY_LIMIT = self.LIMIT

    def send(self, client):
        return post_json(client, CHAT_URL, {"message": "Une IPA ?"})

    def test_default_limit_is_ten_per_day(self):
        from pokebeer import settings as project_settings
        assert project_settings.CHAT_DAILY_LIMIT == 10

    def test_requests_beyond_the_daily_limit_are_refused_before_calling_ai(self, auth_client, zythologue):
        statuses = [self.send(auth_client).status_code for _ in range(self.LIMIT + 1)]
        assert statuses == [200] * self.LIMIT + [429]
        assert zythologue.call_count == self.LIMIT

    def test_refusal_message_is_shown_in_the_chat(self, auth_client, zythologue):
        for _ in range(self.LIMIT):
            self.send(auth_client)
        assert "demain" in self.send(auth_client).json()["response"]

    def test_quota_survives_a_new_session(self, client_for, user, zythologue):
        for _ in range(self.LIMIT):
            self.send(client_for(user))
        assert self.send(client_for(user)).status_code == 429

    def test_quota_is_per_user(self, auth_client, other_client, zythologue):
        for _ in range(self.LIMIT):
            self.send(auth_client)
        assert self.send(other_client).status_code == 200

    def test_failed_ai_calls_still_count(self, auth_client):
        for _ in range(self.LIMIT):
            self.send(auth_client)
        assert self.send(auth_client).status_code == 429

    def test_reading_history_does_not_use_quota(self, auth_client, zythologue):
        for _ in range(self.LIMIT + 5):
            auth_client.get(CHAT_URL)
        assert self.send(auth_client).status_code == 200


class TestAnalyzeLabel:
    def upload(self, client):
        return client.post(LABEL_URL, {"image": f.make_image_upload()})

    def test_image_is_required(self, auth_client):
        assert auth_client.post(LABEL_URL).status_code == 400

    @pytest.mark.parametrize("raw", ['{"name": "Punk IPA", "degree": 5.6}', '```json\n{"name": "Punk IPA", "degree": 5.6}\n```'])
    def test_returns_parsed_json_even_inside_markdown_fence(self, auth_client, label_client, raw):
        label_client.models.generate_content.return_value = SimpleNamespace(text=raw)
        assert self.upload(auth_client).json() == {"success": True, "data": {"name": "Punk IPA", "degree": 5.6}}

    def test_image_is_sent_with_its_mime_type(self, auth_client, label_client):
        label_client.models.generate_content.return_value = SimpleNamespace(text="{}")
        self.upload(auth_client)
        image_part = label_client.models.generate_content.call_args.kwargs["contents"][1]
        assert image_part.inline_data.mime_type == "image/png"

    def test_unparseable_ai_answer_is_a_server_error(self, auth_client, label_client):
        label_client.models.generate_content.return_value = SimpleNamespace(text="Je ne sais pas")
        assert self.upload(auth_client).status_code == 500

    def test_declared_type_is_never_trusted(self, auth_client, label_client):
        label_client.models.generate_content.return_value = SimpleNamespace(text="{}")
        upload = f.make_image_upload()
        upload.content_type = "application/x-evil"
        auth_client.post(LABEL_URL, {"image": upload})
        assert label_client.models.generate_content.call_args.kwargs["contents"][1].inline_data.mime_type == "image/png"

    @pytest.mark.parametrize("payload", [b"<svg onload=alert(1)>", b"GIF89a....", b"not an image", b""])
    def test_non_images_are_refused_before_the_ai_is_called(self, auth_client, label_client, payload):
        from django.core.files.uploadedfile import SimpleUploadedFile
        response = auth_client.post(LABEL_URL, {"image": SimpleUploadedFile("x.png", payload, content_type="image/png")})
        assert response.status_code == 400
        label_client.models.generate_content.assert_not_called()

    def test_oversized_images_are_refused(self, auth_client, label_client, settings):
        settings.LABEL_MAX_UPLOAD_BYTES = 10
        assert self.upload(auth_client).status_code == 400
        label_client.models.generate_content.assert_not_called()

    def test_daily_quota_is_enforced_and_separate_from_chat(self, auth_client, label_client, settings, zythologue):
        settings.LABEL_DAILY_LIMIT = 2
        label_client.models.generate_content.return_value = SimpleNamespace(text="{}")
        assert [self.upload(auth_client).status_code for _ in range(3)] == [200, 200, 429]
        assert post_json(auth_client, CHAT_URL, {"message": "Salut"}).status_code == 200

    def test_invalid_images_do_not_use_the_quota(self, auth_client, label_client, settings):
        from django.core.files.uploadedfile import SimpleUploadedFile
        settings.LABEL_DAILY_LIMIT = 1
        auth_client.post(LABEL_URL, {"image": SimpleUploadedFile("x.png", b"junk", content_type="image/png")})
        label_client.models.generate_content.return_value = SimpleNamespace(text="{}")
        assert self.upload(auth_client).status_code == 200

    def test_internal_error_details_are_not_leaked(self, auth_client, label_client):
        label_client.models.generate_content.side_effect = RuntimeError("api key=SECRET-123 rejected")
        response = self.upload(auth_client)
        assert response.status_code == 500 and "SECRET-123" not in response.content.decode()

    def test_ai_outage_is_a_server_error(self, auth_client):
        assert "error" in self.upload(auth_client).json()
