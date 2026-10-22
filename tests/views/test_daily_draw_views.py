"""Tirage du jour : accueil et API."""
import pytest
from django.urls import reverse

from app.models import DailyDraw
from app.services.catalog import daily_draw
from tests import factories as f

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalogue():
    return [f.make_beer() for _ in range(8)]


class TestHome:
    def test_the_button_replaces_the_chat_shortcut(self, auth_client, catalogue):
        html = auth_client.get(reverse("index")).content.decode()
        assert "data-draw-open" in html and "data-open-chat" not in html and "script/daily_draw.js" in html

    def test_a_finished_draw_stays_reachable_all_day_as_a_summary(self, auth_client, user, catalogue):
        daily_draw.open_today(user)
        daily_draw.reveal(user, daily_draw.CARDS)
        html = auth_client.get(reverse("index")).content.decode()
        assert 'data-state="done"' in html and "data-draw-open" in html and "Revoir mes bières du jour" in html

    def test_reopening_a_finished_draw_returns_the_same_cards_all_revealed(self, auth_client, user, catalogue):
        first = auth_client.post(reverse("open_daily_draw")).json()
        auth_client.post(reverse("reveal_daily_draw"), {"count": 5}, content_type="application/json")
        again = auth_client.post(reverse("open_daily_draw")).json()
        assert again["revealed"] == 5 and [c["slug"] for c in again["cards"]] == [c["slug"] for c in first["cards"]]
        assert all(c["beer_url"] for c in again["cards"])  # chaque bière du résumé mène à sa fiche

    def test_an_unfinished_draw_can_be_resumed(self, auth_client, user, catalogue):
        daily_draw.open_today(user)
        html = auth_client.get(reverse("index")).content.decode()
        assert "data-draw-open" in html and "Reprenez" in html

    def test_nothing_when_the_member_tasted_everything(self, auth_client, user):
        f.make_drink(user, f.make_beer())
        html = auth_client.get(reverse("index")).content.decode()
        assert "data-draw-open" not in html


class TestOpen:
    def test_returns_five_cards_with_what_the_page_needs(self, auth_client, catalogue):
        response = auth_client.post(reverse("open_daily_draw"))
        cards = response.json()["cards"]
        assert response.status_code == 200 and len(cards) == 5
        assert {"rarity", "rarity_label", "name", "brewery", "style", "degree", "image", "beer_url", "rate_url", "slug", "in_wishlist"} <= set(cards[0])

    def test_reopening_gives_the_same_cards(self, auth_client, catalogue):
        first = auth_client.post(reverse("open_daily_draw")).json()["cards"]
        again = auth_client.post(reverse("open_daily_draw")).json()["cards"]
        assert [c["slug"] for c in first] == [c["slug"] for c in again]

    def test_wishlist_state_is_reported(self, auth_client, user, catalogue):
        card = auth_client.post(reverse("open_daily_draw")).json()["cards"][0]
        user.wishlist_beers.add(*[b for b in catalogue if b.slug == card["slug"]])
        again = auth_client.post(reverse("open_daily_draw")).json()["cards"][0]
        assert not card["in_wishlist"] and again["in_wishlist"]

    def test_nothing_to_discover_is_a_clean_404(self, auth_client, user):
        f.make_drink(user, f.make_beer())
        assert auth_client.post(reverse("open_daily_draw")).status_code == 404

    def test_get_is_refused_and_anonymous_is_sent_to_login(self, auth_client, client, catalogue):
        assert auth_client.get(reverse("open_daily_draw")).status_code == 405
        response = client.post(reverse("open_daily_draw"))
        assert response.status_code == 302 and "login" in response["Location"]
        assert not DailyDraw.objects.exists()


class TestReveal:
    def post(self, client, body):
        return client.post(reverse("reveal_daily_draw"), body, content_type="application/json")

    def test_the_progress_is_returned_when_the_draw_is_reopened(self, auth_client, catalogue):
        auth_client.post(reverse("open_daily_draw"))
        assert self.post(auth_client, {"count": 2}).json() == {"success": True, "revealed": 2}
        assert auth_client.post(reverse("open_daily_draw")).json()["revealed"] == 2

    def test_revealing_everything_finishes_the_draw(self, auth_client, user, catalogue):
        auth_client.post(reverse("open_daily_draw"))
        self.post(auth_client, {"count": 5})
        assert DailyDraw.objects.get(user=user).completed_at is not None

    @pytest.mark.parametrize("body", [{}, {"count": "3"}, {"count": True}, {"count": -1}, {"count": 1.5}, [1]])
    def test_invalid_counts_are_refused(self, auth_client, catalogue, body):
        auth_client.post(reverse("open_daily_draw"))
        assert self.post(auth_client, body).status_code == 400

    def test_not_json_is_refused(self, auth_client, catalogue):
        auth_client.post(reverse("open_daily_draw"))
        assert auth_client.post(reverse("reveal_daily_draw"), "oops", content_type="application/json").status_code == 400

    def test_without_a_draw_there_is_nothing_to_reveal(self, auth_client):
        assert self.post(auth_client, {"count": 1}).status_code == 404

    def test_get_is_refused(self, auth_client):
        assert auth_client.get(reverse("reveal_daily_draw")).status_code == 405

    def test_one_member_cannot_move_another_members_progress(self, auth_client, other_client, catalogue, other_user):
        auth_client.post(reverse("open_daily_draw"))
        other_client.post(reverse("open_daily_draw"))
        self.post(auth_client, {"count": 4})
        assert DailyDraw.objects.get(user=other_user).revealed == 0


class TestRateLink:
    def test_the_rating_link_opens_the_beer_page_with_its_rating_window(self, auth_client, catalogue):
        card = auth_client.post(reverse("open_daily_draw")).json()["cards"][0]
        assert card["rate_url"] == f"{card['beer_url']}#modalRate-{card['slug']}"
        html = auth_client.get(card["beer_url"]).content.decode()
        assert f'id="modalRate-{card["slug"]}"' in html  # la fenêtre ciblée par le lien existe sur la fiche


class TestCron:
    def test_the_reminder_endpoint_requires_the_secret(self, client, settings):
        settings.CRON_SECRET = "s3cret"
        url = reverse("cron_daily_draw_reminder")
        assert client.get(url).status_code == 403
        assert client.get(url, headers={"Authorization": "Bearer nope"}).status_code == 403
        response = client.get(url, headers={"Authorization": "Bearer s3cret"})
        assert response.status_code == 200 and response.json() == {"draw_reminders": 0}

    def test_closed_without_a_configured_secret(self, client, settings):
        settings.CRON_SECRET = None
        assert client.get(reverse("cron_daily_draw_reminder"), headers={"Authorization": "Bearer None"}).status_code == 403


class TestKillSwitch:
    SECTION = "account_settings"

    def test_the_settings_page_lists_the_section_and_shows_the_toggle_on(self, auth_client):
        assert "Tirage du jour" in auth_client.get(reverse("account_settings_home")).content.decode()
        html = auth_client.get(reverse(self.SECTION, args=["draw"])).content.decode()
        assert 'name="daily_draw_enabled"' in html and "checked" in html.split('name="daily_draw_enabled"')[1].split(">")[0]

    def test_unchecking_the_toggle_disables_the_feature(self, auth_client, user, catalogue):
        response = auth_client.post(reverse(self.SECTION, args=["draw"]), {"btn_draw": ""})  # case décochée : champ absent
        user.refresh_from_db()
        assert response.status_code == 302 and user.daily_draw_enabled is False
        html = auth_client.get(reverse("index")).content.decode()
        assert "data-draw-open" not in html

    def test_checking_it_again_brings_the_button_back(self, auth_client, user, catalogue):
        auth_client.post(reverse(self.SECTION, args=["draw"]), {"btn_draw": ""})
        auth_client.post(reverse(self.SECTION, args=["draw"]), {"btn_draw": "", "daily_draw_enabled": "on"})
        assert "data-draw-open" in auth_client.get(reverse("index")).content.decode()

    def test_the_server_refuses_the_draw_when_disabled(self, auth_client, user, catalogue):
        user.daily_draw_enabled = False
        user.save()
        for name in ("open_daily_draw", "reveal_daily_draw"):
            assert auth_client.post(reverse(name)).status_code == 403
        assert not DailyDraw.objects.exists()

    def test_the_trophy_is_hidden_on_the_profile_when_disabled(self, auth_client, user):
        assert "Découvreur" in auth_client.get(reverse("achievements")).content.decode()
        auth_client.post(reverse(self.SECTION, args=["draw"]), {"btn_draw": ""})
        assert "Découvreur" not in auth_client.get(reverse("achievements")).content.decode()
