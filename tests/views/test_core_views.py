from datetime import date

import pytest
from django.urls import reverse

from tests import factories as f

pytestmark = pytest.mark.django_db

HOME_LIMIT = 10


class TestHomeSearchAndFriends:
    def test_home_puts_followed_members_first(self, auth_client, user, other_user):
        stranger = f.make_user()
        f.follow(user, other_user)
        friend_beer, stranger_beer = f.make_beer(name="FriendBeer"), f.make_beer(name="StrangerBeer")
        f.make_drink(other_user, friend_beer, note=8)
        f.make_drink(stranger, stranger_beer, note=9)

        response = auth_client.get(reverse("index"))

        assert [t.beer_id.name for t in response.context["activity"]] == ["FriendBeer", "StrangerBeer"]  # amis d'abord, communauté ensuite
        assert [t.is_friend for t in response.context["activity"]] == [True, False]
        assert response.context["activity_kind"] == "mixed"

    def test_friends_feed_hides_blocked_suspended_and_deleted_beers(self, auth_client, user, other_user):
        blocked, suspended = f.make_user(), f.make_user(is_active=False)
        for friend in (other_user, blocked, suspended):
            f.follow(user, friend)
        f.block(user, blocked)
        f.make_drink(blocked, f.make_beer(), note=5)
        f.make_drink(suspended, f.make_beer(), note=5)
        f.make_drink(other_user, f.make_beer(is_deleted=True), note=5)

        assert auth_client.get(reverse("index")).context["activity"] == []

    def test_friends_feed_is_newest_first(self, auth_client, user, other_user):
        f.follow(user, other_user)
        for index in range(7):
            f.make_drink(other_user, f.make_beer(), note=5, date=date(2024, 1, index + 1))
        feed = auth_client.get(reverse("index")).context["activity"]
        assert len(feed) == 7 and [t.date.day for t in feed] == [7, 6, 5, 4, 3, 2, 1]

    def test_home_query_count_does_not_grow_with_friends(self, auth_client, user, django_assert_max_num_queries):
        friends = [f.make_user() for _ in range(5)]
        for friend in friends:
            f.follow(user, friend)
            f.make_drink(friend, f.make_beer(), note=8)
        with django_assert_max_num_queries(20):  # fixe : un ami de plus ne doit pas ajouter de requête (avatars, brasseries préchargés)
            assert auth_client.get(reverse("index")).status_code == 200

    def test_home_is_lean_it_no_longer_ranks_or_lists_unrated_beers(self, auth_client):
        context = auth_client.get(reverse("index")).context
        assert "top" not in context and "unrated_beers" not in context

    def test_home_without_search_shows_home_sections(self, auth_client):
        response = auth_client.get(reverse("index"))
        assert response.context["searching"] is False
        assert 'id="home-sections" class=""' in response.content.decode()

    def test_home_with_query_renders_search_results_and_hides_home(self, auth_client):
        f.make_beer(name="Zythos Unique")

        response = auth_client.get(reverse("index"), {"q": "Zythos"})

        body = response.content.decode()
        assert response.context["searching"] is True
        assert "Zythos Unique" in body
        assert 'id="home-sections" class="hidden"' in body


class TestHome:
    def test_page_sets_csrf_cookie_for_javascript(self, auth_client):
        assert "csrftoken" in auth_client.get(reverse("index")).cookies

    def test_service_role_key_never_reaches_the_browser(self, auth_client, settings):
        settings.SUPABASE_SERVICE_ROLE_KEY = "service-role-secret-value"
        assert b"service-role-secret-value" not in auth_client.get(reverse("index")).content


class TestAllBeers:
    def test_beers_tab_by_default_with_split_styles(self, auth_client):
        f.make_beer(style="Stout, IPA")
        f.make_beer(style="IPA")
        f.make_beer(style="Porter", is_deleted=True)
        context = auth_client.get(reverse("all_beers")).context
        assert (context["active_tab"], context["styles"]) == ("beers", ["IPA", "Stout"])

    @pytest.mark.parametrize("params", [{"uq": "bob"}, {"tab": "members"}])
    def test_members_tab(self, auth_client, params):
        assert auth_client.get(reverse("all_beers"), params).context["active_tab"] == "members"

    def test_first_page_is_capped_at_ten(self, auth_client):
        for _ in range(HOME_LIMIT + 1):
            f.make_beer()
        assert len(auth_client.get(reverse("all_beers"), {"tab": "beers"}).context["beers"]) == HOME_LIMIT

    def test_hostile_search_input_is_escaped(self, auth_client):
        payload = "<script>alert(1)</script>"
        content = auth_client.get(reverse("all_beers"), {"q": payload, "uq": payload}).content
        assert payload.encode() not in content


class TestCommunityFallback:
    def test_without_friends_the_community_is_shown_instead(self, auth_client, user, other_user):
        f.make_drink(other_user, f.make_beer(name="CommunityBeer"), note=8)
        f.make_drink(user, f.make_beer(name="MyOwnBeer"), note=9)

        response = auth_client.get(reverse("index"))
        body = response.content.decode()

        assert response.context["activity_kind"] == "community"
        assert [t.beer_id.name for t in response.context["activity"]] == ["CommunityBeer"]  # jamais mes propres dégustations
        assert "La communauté a goûté" in body and "Vos amis ont goûté" not in body
        assert "Suivez des membres" in body
        assert response.context["activity"][0].is_friend is False

    def test_following_someone_with_tastings_switches_to_friends(self, auth_client, user, other_user):
        stranger = f.make_user()
        f.make_drink(stranger, f.make_beer(name="StrangerBeer"), note=8)
        f.make_drink(other_user, f.make_beer(name="FriendBeer"), note=7)
        f.follow(user, other_user)

        context = auth_client.get(reverse("index")).context

        assert context["activity_kind"] == "mixed"
        assert [t.beer_id.name for t in context["activity"]] == ["FriendBeer", "StrangerBeer"]

    def test_friends_without_tastings_fall_back_to_the_community(self, auth_client, user, other_user):
        f.follow(user, other_user)
        f.make_drink(f.make_user(), f.make_beer(name="CommunityBeer"), note=6)
        context = auth_client.get(reverse("index")).context
        assert context["activity_kind"] == "community" and len(context["activity"]) == 1

    def test_community_hides_blocked_suspended_and_removed_beers(self, auth_client, user):
        blocked, suspended, fine = f.make_user(), f.make_user(is_active=False), f.make_user()
        f.block(user, blocked)
        f.make_drink(blocked, f.make_beer(), note=5)
        f.make_drink(suspended, f.make_beer(), note=5)
        f.make_drink(fine, f.make_beer(is_deleted=True), note=5)
        f.make_drink(fine, f.make_beer(name="Visible"), note=5, comment="ok")
        assert [t.beer_id.name for t in auth_client.get(reverse("index")).context["activity"]] == ["Visible"]

    def test_community_home_query_count_is_bounded(self, auth_client, other_user, django_assert_max_num_queries):
        for _ in range(8):
            f.make_drink(f.make_user(), f.make_beer(), note=7)
        with django_assert_max_num_queries(20):
            assert auth_client.get(reverse("index")).status_code == 200


class TestActivityCards:
    def test_friends_come_first_and_the_community_completes_to_ten(self, auth_client, user, other_user):
        f.follow(user, other_user)
        stranger = f.make_user()
        f.make_drink(other_user, f.make_beer(name="Ami ancien"), note=8, date=date(2020, 1, 1))
        f.make_drink(other_user, f.make_beer(name="Ami récent"), note=8, date=date(2021, 1, 1))
        for index in range(5):  # plus récentes que celles des amis, mais elles ne passent qu'après
            f.make_drink(stranger, f.make_beer(name=f"Inconnu {index}"), note=6, date=date(2024, 1, index + 1))

        context = auth_client.get(reverse("index")).context
        names = [t.beer_id.name for t in context["activity"]]

        assert names[:2] == ["Ami récent", "Ami ancien"] and len(names) == 7
        assert [t.is_friend for t in context["activity"]] == [True, True] + [False] * 5
        assert names[2:] == ["Inconnu 4", "Inconnu 3", "Inconnu 2", "Inconnu 1", "Inconnu 0"]
        assert context["activity_kind"] == "mixed" and context["activity_title"] == "Vos amis et la communauté"

    def test_with_more_than_ten_friend_tastings_only_the_latest_ten_are_shown(self, auth_client, user, other_user):
        f.follow(user, other_user)
        for index in range(12):
            f.make_drink(other_user, f.make_beer(name=f"Ami {index}"), note=7, date=date(2024, 2, index + 1))
        f.make_drink(f.make_user(), f.make_beer(name="Inconnu"), note=7)
        names = [t.beer_id.name for t in auth_client.get(reverse("index")).context["activity"]]
        assert names == [f"Ami {index}" for index in range(11, 1, -1)]

    def test_the_card_shows_the_member_avatar_and_keeps_the_recommendation_pattern(self, auth_client, other_user):
        f.make_drink(other_user, f.make_beer(name="Carte Test"), note=9)
        html = auth_client.get(reverse("index")).content.decode()
        at = html.index('aria-label="Carte Test')
        card = html[html.rindex("<a ", 0, at):html.index("</a>", at)]
        assert "absolute top-1.5 right-1.5" in card and other_user.avatar_url in card
        assert "w-[44%]" in card and "snap-start" in card

class TestHomeNearbyAndGaetan:
    def test_nearby_section_is_rendered_directly_with_the_100_km_rule(self, auth_client):
        html = auth_client.get(reverse("index")).content.decode()
        assert 'id="home-nearby"' in html and 'data-radius-km="100"' in html and 'data-fallback="3"' in html
        assert "Voir les bars et brasseries près de moi" not in html  # plus de bouton à cliquer

    def test_nearby_tab_keeps_its_unbounded_behaviour(self, auth_client):
        html = auth_client.get(reverse("all_beers"), {"tab": "nearby"}).content.decode()
        assert "data-nearby" in html and "data-radius-km" not in html

    def test_gaetan_button_opens_the_chat_without_prefilling_it(self, auth_client):
        html = auth_client.get(reverse("index")).content.decode()
        assert "data-open-chat" in html
        chat_input = html[html.index('id="chat-input"'):].split(">", 1)[0]
        assert "value=" not in chat_input
        assert "Une bière douce pour ce soir" not in html


class TestGaetanButtonWiring:
    def test_chat_elements_come_after_the_page_content_so_the_script_must_look_them_up_on_click(self, auth_client):
        html = auth_client.get(reverse("index")).content.decode()
        assert html.index("data-open-chat") < html.index('id="chat-toggle"') < html.index('id="chat-window"')
