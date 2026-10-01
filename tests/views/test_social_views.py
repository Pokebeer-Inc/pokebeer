import pytest
from django.urls import reverse

from app.models import Beer, BeerUser, DrinkReaction, Drinks, Feedback, Notification, UserFollow
from tests import factories as f
from tests.helpers import assert_redirects, messages_of, post_json

pytestmark = pytest.mark.django_db


class TestAccount:
    URL = reverse("account")

    def test_page_renders_with_statistics(self, auth_client, user, beer):
        f.make_drink(user, beer, note=8)
        response = auth_client.get(self.URL)
        assert response.status_code == 200
        assert response.context["total_drinks"] == 1

    def test_profile_update(self, auth_client, user):
        auth_client.post(self.URL, {"btn_profile": "", "username": "alice", "email": "new@example.test", "bio": "Hop"})
        user.refresh_from_db()
        assert (user.email, user.bio) == ("new@example.test", "Hop")

    def test_profile_update_cannot_take_another_username(self, auth_client, user, other_user):
        auth_client.post(self.URL, {"btn_profile": "", "username": other_user.username, "email": user.email})
        user.refresh_from_db()
        assert user.username == "alice"

    def test_password_change_keeps_the_session(self, auth_client, user):
        new_password = "Another-Str0ng-Pass!"
        auth_client.post(self.URL, {"btn_password": "", "old_password": f.PASSWORD, "new_password1": new_password, "new_password2": new_password})
        user.refresh_from_db()
        assert user.check_password(new_password)
        assert auth_client.get(self.URL).status_code == 200

    def test_password_change_requires_old_password(self, auth_client, user):
        auth_client.post(self.URL, {"btn_password": "", "old_password": "nope", "new_password1": "Xx-12345678", "new_password2": "Xx-12345678"})
        user.refresh_from_db()
        assert user.check_password(f.PASSWORD)

    def test_feedback_is_attached_to_current_user(self, auth_client, user):
        auth_client.post(self.URL, {"btn_feedback": "", "message": "Bravo"})
        assert Feedback.objects.get().user == user

    def test_empty_feedback_is_refused(self, auth_client):
        auth_client.post(self.URL, {"btn_feedback": "", "message": ""})
        assert not Feedback.objects.exists()

    def test_unchecked_notification_preferences_are_disabled(self, auth_client, user):
        auth_client.post(self.URL, {"btn_notifs": "", "notif_global": "on"})
        user.refresh_from_db()
        assert user.notif_global and not (user.notif_follow or user.notif_social or user.notif_network or user.notif_achievements)

    def test_pro_visibility_setting(self, auth_client, user):
        auth_client.post(self.URL, {"btn_pro_settings": ""})
        user.refresh_from_db()
        assert not user.show_establishments


class TestDeleteAccount:
    URL = reverse("delete_account")

    def test_get_does_not_delete(self, auth_client, user):
        assert_redirects(auth_client.get(self.URL), reverse("account"))
        assert BeerUser.objects.filter(pk=user.pk).exists()

    def test_post_deletes_personal_data_but_keeps_catalogue(self, auth_client, user):
        added = f.make_beer(added_by=user)
        f.make_drink(user, added)
        auth_client.post(self.URL)
        assert not BeerUser.objects.filter(pk=user.pk).exists()
        assert not Drinks.objects.exists()
        assert Beer.objects.get(pk=added.pk).added_by is None
        assert "_auth_user_id" not in auth_client.session


class TestPublicProfile:
    def url(self, username):
        return reverse("public_profile", args=[username])

    def test_own_profile_redirects_to_account(self, auth_client):
        assert_redirects(auth_client.get(self.url("alice")), reverse("account"))

    def test_unknown_user_is_404(self, auth_client):
        assert auth_client.get(self.url("ghost")).status_code == 404

    def test_profile_shows_following_state(self, auth_client, user, other_user):
        f.follow(user, other_user)
        response = auth_client.get(self.url(other_user.username))
        assert response.status_code == 200
        assert response.context["is_following"]

    @pytest.mark.parametrize("i_block", [True, False])
    def test_blocked_profiles_are_inaccessible_both_ways(self, auth_client, user, other_user, i_block):
        f.block(*((user, other_user) if i_block else (other_user, user)))
        assert_redirects(auth_client.get(self.url(other_user.username)), reverse("index"))

    def test_only_ten_latest_drinks_are_rendered(self, auth_client, other_user):
        for _ in range(11):
            f.make_drink(other_user)
        response = auth_client.get(self.url(other_user.username))
        assert (len(response.context["user_drinks"]), response.context["total_drinks"]) == (10, 11)


class TestFollow:
    def test_follow_then_unfollow(self, auth_client, user, other_user):
        url = reverse("follow_user", args=[other_user.username])
        auth_client.post(url)
        assert UserFollow.objects.filter(follower=user, followed=other_user).exists()
        assert Notification.objects.get().notif_type == "follow"

        auth_client.post(url)
        assert not UserFollow.objects.exists()

    def test_cannot_follow_oneself(self, auth_client):
        auth_client.post(reverse("follow_user", args=["alice"]))
        assert not UserFollow.objects.exists()

    def test_unknown_user_is_404(self, auth_client):
        assert auth_client.post(reverse("follow_user", args=["ghost"])).status_code == 404

    def test_redirects_back_to_referer(self, auth_client, other_user):
        response = auth_client.post(reverse("follow_user", args=[other_user.username]), HTTP_REFERER="/beers/")
        assert_redirects(response, "/beers/")

    def test_remove_follower_requires_post(self, auth_client, user, other_user):
        f.follow(other_user, user)
        url = reverse("remove_follower", args=[other_user.username])
        auth_client.get(url)
        assert UserFollow.objects.exists()
        auth_client.post(url)
        assert not UserFollow.objects.exists()


class TestReactions:
    @pytest.fixture
    def drink(self, other_user, beer):
        return f.make_drink(other_user, beer)

    def react(self, client, drink, **payload):
        return post_json(client, reverse("toggle_reaction", args=[drink.slug]), payload)

    def test_like_creates_reaction_and_notifies_author(self, auth_client, drink):
        body = self.react(auth_client, drink, is_like=True).json()
        assert body == {"success": True, "score": 1, "likes": 1, "dislikes": 0, "current_reaction": True}
        assert Notification.objects.get().recipient == drink.drinker_id

    def test_same_reaction_twice_cancels_it(self, auth_client, drink):
        self.react(auth_client, drink, is_like=False)
        body = self.react(auth_client, drink, is_like=False).json()
        assert (body["score"], body["current_reaction"]) == (0, None)
        assert not DrinkReaction.objects.exists()

    def test_switching_reaction(self, auth_client, drink):
        self.react(auth_client, drink, is_like=True)
        body = self.react(auth_client, drink, is_like=False).json()
        assert (body["score"], body["likes"], body["dislikes"]) == (-1, 0, 1)

    def test_dislike_does_not_notify(self, auth_client, drink):
        self.react(auth_client, drink, is_like=False)
        assert not Notification.objects.exists()

    def test_score_aggregates_all_users(self, auth_client, drink):
        f.react(f.make_user(), drink, is_like=True)
        f.react(f.make_user(), drink, is_like=True)
        assert self.react(auth_client, drink, is_like=False).json()["score"] == 1

    def test_cannot_react_to_own_review(self, other_client, drink):
        assert self.react(other_client, drink, is_like=True).status_code == 400
        assert not DrinkReaction.objects.exists()

    @pytest.mark.parametrize("raw", ["not json", '{"is_like": null}', "{}"])
    def test_invalid_payload_is_rejected(self, auth_client, drink, raw):
        response = post_json(auth_client, reverse("toggle_reaction", args=[drink.slug]), raw=raw)
        assert response.status_code == 400
        assert not DrinkReaction.objects.exists()

    def test_unknown_review_is_rejected(self, auth_client):
        response = post_json(auth_client, reverse("toggle_reaction", args=["unknown-slug"]), {"is_like": True})
        assert response.status_code in (400, 404)


class TestTopBeers:
    def update(self, client, slot, beer_slug=""):
        return client.post(reverse("update_top_beer", args=[slot]), {"beer_slug": beer_slug})

    def test_set_and_clear_a_slot(self, auth_client, user, beer):
        self.update(auth_client, 2, beer.slug)
        user.refresh_from_db()
        assert user.top_beer_2 == beer
        self.update(auth_client, 2)
        user.refresh_from_db()
        assert user.top_beer_2 is None

    @pytest.mark.parametrize("slot", [0, 4, 99])
    def test_out_of_range_slot_is_refused(self, auth_client, user, beer, slot):
        self.update(auth_client, slot, beer.slug)
        user.refresh_from_db()
        assert (user.top_beer_1, user.top_beer_2, user.top_beer_3) == (None, None, None)

    def test_same_beer_cannot_fill_two_slots(self, auth_client, user, beer):
        self.update(auth_client, 1, beer.slug)
        response = self.update(auth_client, 3, beer.slug)
        user.refresh_from_db()
        assert user.top_beer_3 is None
        assert "déjà dans votre Top 3" in messages_of(response)[-1]

    def test_unknown_beer_is_404(self, auth_client):
        assert self.update(auth_client, 1, "unknown-slug").status_code == 404

    def test_swap(self, auth_client, user, beer):
        user.top_beer_1 = beer
        user.save()
        assert post_json(auth_client, reverse("swap_top_beers"), {"from_slot": 1, "to_slot": 3}).json() == {"success": True}
        user.refresh_from_db()
        assert (user.top_beer_1, user.top_beer_3) == (None, beer)

    @pytest.mark.parametrize("payload", [{"from_slot": 0, "to_slot": 1}, {"from_slot": 1, "to_slot": 4}, {"from_slot": "a", "to_slot": 1}, {}])
    def test_swap_rejects_invalid_slots(self, auth_client, payload):
        assert post_json(auth_client, reverse("swap_top_beers"), payload).status_code == 400

    def test_swap_rejects_malformed_json(self, auth_client):
        assert post_json(auth_client, reverse("swap_top_beers"), raw="{oops").status_code == 400


class TestWishlist:
    def toggle(self, client, beer):
        return client.post(reverse("toggle_wishlist", args=[beer.slug])).json()

    def test_toggle_adds_then_removes(self, auth_client, user, beer):
        assert self.toggle(auth_client, beer) == {"success": True, "is_in_wishlist": True}
        assert self.toggle(auth_client, beer) == {"success": True, "is_in_wishlist": False}
        assert not user.wishlist_beers.exists()

    def test_creator_is_notified_but_not_when_it_is_his_own_beer(self, auth_client, other_client, beer):
        self.toggle(auth_client, beer)
        self.toggle(other_client, beer)
        assert list(Notification.objects.values_list("notif_type", "recipient__username")) == [("wishlist_added", "bobby")]

    def test_unknown_beer_is_404(self, auth_client):
        assert auth_client.post(reverse("toggle_wishlist", args=["unknown-slug"])).status_code == 404

    def test_wishlist_page_lists_only_wishlisted_beers(self, auth_client, user, beer):
        f.make_beer(name="Pas voulue")
        user.wishlist_beers.add(beer)
        response = auth_client.get(reverse("wishlist_view"))
        assert [b.name for b in response.context["beers"]] == ["Test IPA"]
        assert response.context["styles"] == ["IPA"]


def test_achievements_page(auth_client):
    response = auth_client.get(reverse("achievements"))
    assert response.status_code == 200
    assert response.context["level_data"]["current_level"] == 1
