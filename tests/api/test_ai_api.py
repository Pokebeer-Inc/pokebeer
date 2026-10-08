from types import SimpleNamespace
from unittest import mock

from datetime import timedelta

import pytest
from django.urls import reverse

from app.services.chat import ChatUnavailable
from app.services.throttle import Rule

from tests import factories as f
from tests.helpers import post_json

pytestmark = pytest.mark.django_db

CHAT_URL = reverse("chat_api")
LABEL_URL = reverse("analyze_label")
HISTORY_LIMIT = 10


@pytest.fixture
def zythologue(monkeypatch):
    ask = mock.Mock(side_effect=lambda message, history, location=None: f"Réponse à {message}")
    monkeypatch.setattr("app.views.api_views.ask_zythologue", ask)
    return ask


@pytest.fixture(autouse=True)
def no_burst_limit(monkeypatch):
    """Les tests envoient de nombreux messages d'affilée : la rafale a ses propres tests (TestChatLimits)."""
    monkeypatch.setattr("app.views.api_views.CHAT_BURST_BY_USER", Rule("chat-burst", 10_000, timedelta(minutes=1)))


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

    def test_ai_outage_is_reported_without_losing_the_question(self, auth_client, monkeypatch, user):
        monkeypatch.setattr("app.views.api_views.ask_zythologue", mock.Mock(side_effect=ChatUnavailable))
        response = post_json(auth_client, CHAT_URL, {"message": "Bonjour"})
        assert response.status_code == 503 and response.json()["response"].startswith("Désolé")
        assert auth_client.get(CHAT_URL).json() == {"history": []}
        assert not user.chat_usages.filter(count__gt=0).exists()

    def test_location_is_validated_rounded_and_never_stored(self, auth_client, zythologue):
        post_json(auth_client, CHAT_URL, {"message": "Un bar ?", "location": {"lat": 48.85661, "lng": 2.35222}})
        location = zythologue.call_args.args[2]
        assert (location.lat, location.lng) == (48.86, 2.35)
        assert "48" not in str(auth_client.get(CHAT_URL).json())

    @pytest.mark.parametrize("location", [{"lat": 99, "lng": 2}, {"lat": "x", "lng": 2}, {"lat": 1}, "Paris", [1, 2], {"lat": float("nan"), "lng": 1}])
    def test_invalid_location_is_ignored(self, auth_client, zythologue, location):
        assert post_json(auth_client, CHAT_URL, {"message": "Un bar ?", "location": location}).status_code == 200
        assert zythologue.call_args.args[2] is None

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

    def test_default_limits_are_ten_per_day_and_forty_per_week(self):
        from pokebeer import settings as project_settings
        assert (project_settings.CHAT_DAILY_LIMIT, project_settings.CHAT_WEEKLY_LIMIT) == (10, 40)

    def test_weekly_limit_stops_a_member_who_spends_the_daily_limit_every_day(self, auth_client, zythologue, settings, user):
        from datetime import timedelta as days
        from django.utils import timezone
        from app.models import ChatUsage
        settings.CHAT_WEEKLY_LIMIT = 5
        for ago in (1, 2):
            ChatUsage.objects.create(user=user, day=timezone.localdate() - days(days=ago), scope="chat", count=2)
        statuses = [self.send(auth_client).status_code for _ in range(2)]
        assert statuses == [200, 429]

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

    def test_failed_ai_calls_are_refunded_but_still_spend_the_global_budget(self, auth_client):
        from app.services.throttle import CHAT_GLOBAL, CHAT_GLOBAL_KEY
        for _ in range(self.LIMIT + 2):
            assert self.send(auth_client).status_code == 503
        assert CHAT_GLOBAL._hits(CHAT_GLOBAL_KEY).count() == self.LIMIT + 2

    def test_reading_history_does_not_use_quota(self, auth_client, zythologue):
        for _ in range(self.LIMIT + 5):
            auth_client.get(CHAT_URL)
        assert self.send(auth_client).status_code == 200


class TestAnalyzeLabel:
    def upload(self, client):
        return client.post(LABEL_URL, {"image": f.make_image_upload()})

    def test_image_is_required(self, auth_client):
        assert auth_client.post(LABEL_URL).status_code == 400

    @pytest.mark.parametrize("raw", [
        '{"found": true, "name": "Punk IPA", "degree": 5.6}',
        '```json\n{"found": true, "name": "Punk IPA", "degree": 5.6}\n```',
    ])
    def test_returns_parsed_json_even_inside_markdown_fence(self, auth_client, label_client, raw):
        label_client.models.generate_content.return_value = SimpleNamespace(text=raw)
        assert self.upload(auth_client).json() == {"success": True, "data": {"name": "Punk IPA", "brewery": None, "style": None, "degree": 5.6, "bitterness": None}}

    @pytest.mark.parametrize("raw", ['{"found": false}', '{"found": true}', '{}', '{"found": "true", "name": "X"}'])
    def test_an_image_without_an_identified_beer_is_not_an_error(self, auth_client, label_client, raw):
        label_client.models.generate_content.return_value = SimpleNamespace(text=raw)
        response = self.upload(auth_client)
        assert response.status_code == 200 and response.json()["success"] is False and response.json()["not_found"] is True

    def test_the_ai_answer_is_cleaned_before_it_reaches_the_form(self, auth_client, label_client):
        label_client.models.generate_content.return_value = SimpleNamespace(
            text='{"found": true, "name": "<img src=x onerror=alert(1)>Stout", "brewery": 42, "style": "IPA", "degree": 500, "bitterness": "abc", "extra": "x"}'
        )
        data = self.upload(auth_client).json()["data"]
        assert data == {"name": "img src=x onerror=alert(1)Stout", "brewery": None, "style": "IPA", "degree": None, "bitterness": None}

    def test_the_prompt_asks_the_ai_to_say_when_no_beer_is_visible(self, auth_client, label_client):
        label_client.models.generate_content.return_value = SimpleNamespace(text='{"found": false}')
        self.upload(auth_client)
        assert '"found"' in label_client.models.generate_content.call_args.kwargs["contents"][0]

    def test_the_ai_receives_a_reencoded_webp_never_the_original_file(self, auth_client, label_client):
        label_client.models.generate_content.return_value = SimpleNamespace(text="{}")
        self.upload(auth_client)
        image_part = label_client.models.generate_content.call_args.kwargs["contents"][1]
        assert image_part.inline_data.mime_type == "image/webp"
        assert image_part.inline_data.data[:4] == b"RIFF" and image_part.inline_data.data[8:12] == b"WEBP"

    def test_metadata_never_reaches_the_ai(self, auth_client, label_client):
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        exif = Image.Exif()
        exif[0x010E] = "SECRET-GPS-MARKER"
        buffer = BytesIO()
        Image.new("RGB", (4, 4), "orange").save(buffer, "JPEG", exif=exif)
        label_client.models.generate_content.return_value = SimpleNamespace(text="{}")
        auth_client.post(LABEL_URL, {"image": SimpleUploadedFile("x.jpg", buffer.getvalue(), content_type="image/jpeg")})
        assert b"SECRET-GPS-MARKER" not in label_client.models.generate_content.call_args.kwargs["contents"][1].inline_data.data

    def test_ai_failure_gives_the_attempt_back(self, auth_client, label_client, settings):
        settings.LABEL_DAILY_LIMIT = 1
        label_client.models.generate_content.side_effect = RuntimeError("down")
        assert self.upload(auth_client).status_code == 500
        label_client.models.generate_content.side_effect = None
        label_client.models.generate_content.return_value = SimpleNamespace(text="{}")
        assert self.upload(auth_client).status_code == 200

    def test_unparseable_ai_answer_is_a_server_error(self, auth_client, label_client):
        label_client.models.generate_content.return_value = SimpleNamespace(text="Je ne sais pas")
        assert self.upload(auth_client).status_code == 500

    def test_declared_type_is_never_trusted(self, auth_client, label_client):
        label_client.models.generate_content.return_value = SimpleNamespace(text="{}")
        upload = f.make_image_upload()
        upload.content_type = "application/x-evil"
        auth_client.post(LABEL_URL, {"image": upload})
        assert label_client.models.generate_content.call_args.kwargs["contents"][1].inline_data.mime_type == "image/webp"

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


class TestChatLimits:
    @pytest.fixture(autouse=True)
    def real_burst_limit(self, monkeypatch):
        monkeypatch.setattr("app.views.api_views.CHAT_BURST_BY_USER", Rule("chat-burst", 2, timedelta(minutes=1)))

    def test_burst_is_refused_before_calling_ai(self, auth_client, zythologue):
        statuses = [post_json(auth_client, CHAT_URL, {"message": "Une IPA ?"}).status_code for _ in range(3)]
        assert statuses == [200, 200, 429]
        assert zythologue.call_count == 2

    def test_global_budget_protects_the_free_tier(self, auth_client, zythologue, monkeypatch, user):
        monkeypatch.setattr("app.views.api_views.CHAT_GLOBAL", Rule("chat-global", 1, timedelta(days=1)))
        assert post_json(auth_client, CHAT_URL, {"message": "Une IPA ?"}).status_code == 200
        assert post_json(auth_client, CHAT_URL, {"message": "Une IPA ?"}).status_code == 503
        assert zythologue.call_count == 1

    def test_refused_messages_do_not_spend_the_global_budget(self, auth_client, zythologue, settings, monkeypatch):
        settings.CHAT_DAILY_LIMIT = 0
        monkeypatch.setattr("app.views.api_views.CHAT_GLOBAL", Rule("chat-global", 1, timedelta(days=1)))
        assert post_json(auth_client, CHAT_URL, {"message": "Une IPA ?"}).status_code == 429
        settings.CHAT_DAILY_LIMIT = 10
        assert post_json(auth_client, CHAT_URL, {"message": "Une IPA ?"}).status_code == 200
