"""Durcissement : blocages respectés partout, validation des réactions, plafond de notifications, notes uniques, listes paginées."""
import pytest
from django.urls import reverse

from app.models import BeerSpot, BeerUser, CustomNotebook, Drinks, DrinkReaction, Notification, UserFollow
from tests import factories as f
from tests.helpers import post_json

pytestmark = pytest.mark.django_db


class TestBlocksAreRespected:
    def test_a_blocked_member_cannot_follow_the_one_who_blocked_him(self, auth_client, user, other_user):
        f.block(other_user, user)
        assert auth_client.post(reverse("follow_user", args=[other_user.username])).status_code == 404
        assert not UserFollow.objects.exists()

    def test_the_one_who_blocked_cannot_follow_either(self, auth_client, user, other_user):
        f.block(user, other_user)
        assert auth_client.post(reverse("follow_user", args=[other_user.username])).status_code == 404

    def test_cannot_react_to_the_review_of_a_blocked_member(self, auth_client, user, other_user, beer):
        drink = f.make_drink(other_user, beer)
        f.block(other_user, user)
        assert post_json(auth_client, reverse("toggle_reaction", args=[drink.slug]), {"is_like": True}).status_code == 404
        assert not DrinkReaction.objects.exists()

    def test_cannot_react_to_the_review_of_a_suspended_member(self, auth_client, other_user, beer):
        drink = f.make_drink(other_user, beer)
        BeerUser.objects.filter(pk=other_user.pk).update(is_active=False)
        assert post_json(auth_client, reverse("toggle_reaction", args=[drink.slug]), {"is_like": True}).status_code == 404

    def test_cannot_add_a_blocked_members_beer_to_the_wishlist_but_can_still_remove_it(self, auth_client, user, other_user, beer):
        user.wishlist_beers.add(beer)
        f.block(other_user, user)
        assert auth_client.post(reverse("toggle_wishlist", args=[beer.slug])).json()["is_in_wishlist"] is False  # retirer reste possible
        assert auth_client.post(reverse("toggle_wishlist", args=[beer.slug])).status_code == 404

    def test_cannot_add_a_removed_beer_to_the_wishlist(self, auth_client, beer):
        beer.is_deleted = True
        beer.save()
        assert auth_client.post(reverse("toggle_wishlist", args=[beer.slug])).status_code == 404

    def test_a_blocked_member_cannot_be_invited_to_a_spot(self, auth_client, user, other_user):
        f.block(other_user, user)
        auth_client.post(reverse("map"), {"title": "Lieu", "lat": 48.8, "lng": 2.3, "friends": [other_user.username]})
        assert not BeerSpot.objects.get().friends.exists()

    def test_beer_autocomplete_hides_the_beers_of_blocked_members(self, auth_client, user, other_user, beer):
        assert [b["slug"] for b in auth_client.get(reverse("search_beer"), {"term": beer.name[:4]}).json()] == [beer.slug]
        f.block(other_user, user)
        assert auth_client.get(reverse("search_beer"), {"term": beer.name[:4]}).json() == []

    def test_barcode_lookup_ignores_the_beers_of_blocked_members(self, auth_client, user, other_user, beer, monkeypatch):
        beer.ean = "4006381333931"
        beer.save()
        f.block(other_user, user)
        monkeypatch.setattr("app.views.api_views.product_lookup.fetch", lambda code: None)
        assert "existing" not in auth_client.post(reverse("lookup_ean"), {"ean": "4006381333931"}).json()


class TestReactionValidation:
    @pytest.mark.parametrize("raw", ['{"is_like": "yes"}', '{"is_like": 1}', '{"is_like": null}', "[]", "not json"])
    def test_only_a_real_boolean_is_accepted(self, auth_client, other_user, beer, raw):
        drink = f.make_drink(other_user, beer)
        response = post_json(auth_client, reverse("toggle_reaction", args=[drink.slug]), raw=raw)
        assert response.status_code == 400 and not DrinkReaction.objects.exists()

    def test_the_error_never_exposes_an_internal_message(self, auth_client, other_user, beer):
        drink = f.make_drink(other_user, beer)
        body = post_json(auth_client, reverse("toggle_reaction", args=[drink.slug]), raw='{"is_like": "x"}').json()
        assert body == {"success": False, "error": "Requête invalide."}


class TestDailyAlertCeiling:
    """Un membre est signalé (push, pop-up) pour ses trois premières notifications du jour ; toutes restent dans sa liste."""

    @pytest.fixture
    def supabase(self, settings, monkeypatch):
        from unittest import mock
        settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY = "https://p.supabase.co", "key"
        post = mock.Mock(return_value=mock.Mock(status_code=200))
        monkeypatch.setattr("app.services.messaging.realtime_service.requests.post", post)
        return post

    def notify_many(self, recipient, sender, count):
        from app.services.messaging.notifications import notify
        for _ in range(count):
            notify("beer_added", [recipient], sender=sender)

    def test_only_three_alerts_are_sent_but_every_notification_is_kept(self, supabase, user, other_user):
        self.notify_many(user, other_user, 6)
        assert Notification.objects.filter(recipient=user).count() == 6
        assert supabase.call_count == 3

    def test_the_extra_ones_stay_unread_and_counted(self, supabase, auth_client, user, other_user):
        self.notify_many(user, other_user, 5)
        assert Notification.objects.filter(recipient=user, is_read=False).count() == 5
        assert auth_client.get(reverse("api_unread_notifications")).json()["unread_count"] == 3 + 2

    def test_the_extra_ones_never_pop_up_later(self, supabase, auth_client, user, other_user):
        self.notify_many(user, other_user, 5)
        body = auth_client.get(reverse("api_unread_notifications")).json()
        assert len(body["notifications"]) == 3 and body["unread_count"] == 5

    def test_the_list_page_shows_them_all(self, supabase, auth_client, user, other_user):
        self.notify_many(user, other_user, 6)
        assert len(auth_client.get(reverse("notifications")).context["notifications"]) == 6

    def test_the_ceiling_is_per_member(self, supabase, user, other_user):
        third = f.make_user()
        self.notify_many(user, other_user, 4)
        self.notify_many(third, other_user, 4)
        assert supabase.call_count == 6

    def test_the_ceiling_applies_even_when_no_channel_is_configured(self, user, other_user):
        self.notify_many(user, other_user, 5)
        assert Notification.objects.filter(recipient=user, toasted_at__isnull=True).count() == 3

    def test_a_day_later_alerts_resume(self, supabase, user, other_user):
        from datetime import timedelta
        from django.utils import timezone
        self.notify_many(user, other_user, 4)
        Notification.objects.update(created_at=timezone.now() - timedelta(days=1, minutes=1))
        supabase.reset_mock()
        self.notify_many(user, other_user, 1)
        assert supabase.call_count == 1

    def test_repeated_likes_are_all_listed(self, auth_client, other_user, beer):
        drink = f.make_drink(other_user, beer)
        url = reverse("toggle_reaction", args=[drink.slug])
        for _ in range(8):
            post_json(auth_client, url, {"is_like": True})
        assert Notification.objects.filter(notif_type="drink_liked").count() == 4  # un like sur deux crée une notification


class TestOneRatingPerBeer:
    def test_the_database_refuses_a_second_rating(self, user, beer):
        from django.db import IntegrityError, transaction
        f.make_drink(user, beer)
        with pytest.raises(IntegrityError), transaction.atomic():
            f.make_drink(user, beer)

    def test_rating_twice_in_a_row_keeps_the_first(self, auth_client, user, beer):
        payload = {"date": "2026-01-01", "note": 8, "comment": "Très bonne"}
        auth_client.post(reverse("rate_beer", args=[beer.slug]), payload)
        auth_client.post(reverse("rate_beer", args=[beer.slug]), {**payload, "note": 2})
        assert list(Drinks.objects.values_list("note", flat=True)) == [8]

    def test_a_race_between_two_submissions_is_absorbed(self, auth_client, user, beer, monkeypatch):
        """Les deux requêtes passent le contrôle « déjà noté » ; la contrainte de la base arrête la seconde sans erreur 500."""
        original = Drinks.objects.filter
        calls = {"n": 0}

        def blind_first_check(*args, **kwargs):
            calls["n"] += 1
            return original(pk__in=[]) if calls["n"] == 1 else original(*args, **kwargs)

        f.make_drink(user, beer)
        monkeypatch.setattr(Drinks.objects, "filter", blind_first_check)
        response = auth_client.post(reverse("rate_beer", args=[beer.slug]), {"date": "2026-01-01", "note": 3, "comment": "Doublon"})
        assert response.status_code == 302 and Drinks.objects.count() == 1


class TestTopBeers:
    def test_a_beer_never_tasted_cannot_enter_the_top(self, auth_client, user, beer):
        auth_client.post(reverse("update_top_beer", args=[1]), {"beer_slug": beer.slug})
        user.refresh_from_db()
        assert user.top_beer_1 is None

    def test_a_removed_beer_cannot_enter_the_top(self, auth_client, user, beer):
        f.make_drink(user, beer)
        beer.is_deleted = True
        beer.save()
        assert auth_client.post(reverse("update_top_beer", args=[1]), {"beer_slug": beer.slug}).status_code == 404

    def test_only_the_top_columns_are_saved(self, auth_client, user, beer):
        f.make_drink(user, beer)
        BeerUser.objects.filter(pk=user.pk).update(bio="Modifiée ailleurs")
        auth_client.post(reverse("update_top_beer", args=[1]), {"beer_slug": beer.slug})
        assert BeerUser.objects.get(pk=user.pk).bio == "Modifiée ailleurs"


class TestNotebookTitle:
    def test_markup_in_a_title_is_refused(self, auth_client, user):
        auth_client.post(reverse("create_custom_notebook"), {"title": "<script>alert(1)</script>", "description": ""})
        assert not CustomNotebook.objects.exists()

    def test_an_old_title_with_markup_is_displayed_as_text(self, auth_client, user):
        notebook = CustomNotebook.objects.create(user=user, title="<b>gras</b><img src=x>", description="")
        html = auth_client.get(reverse("notebook_detail", args=[notebook.slug])).content.decode()
        assert "<b>gras</b>" not in html and "&lt;b&gt;gras&lt;/b&gt;" in html


class TestFollowListsArePaged:
    @pytest.fixture
    def crowd(self, user):
        members = [f.make_user() for _ in range(35)]
        for member in members:
            f.follow(member, user)
        return members

    def test_the_profile_shows_exact_counts_but_only_the_first_page(self, auth_client, user, crowd):
        context = auth_client.get(reverse("account")).context
        assert context["followers_count"] == 35 and len(context["followers"]) == 30 and context["followers_has_more"]

    def test_load_more_returns_the_rest_by_pages_of_ten(self, auth_client, user, crowd):
        body = auth_client.get(reverse("load_more_generic", args=["followers"]), {"offset": 30}).json()
        assert body["html"].count("<li") == 5 and body["has_more"] is False

    def test_own_lists_offer_the_remove_buttons_public_ones_do_not(self, auth_client, user, other_user, crowd):
        f.follow(crowd[0], other_user)
        own = auth_client.get(reverse("load_more_generic", args=["followers"]), {"offset": 0}).json()["html"]
        public = auth_client.get(reverse("load_more_generic", args=["followers"]), {"offset": 0, "username": other_user.username}).json()["html"]
        assert "remove-follower" in own and "remove-follower" not in public

    def test_a_blocked_profile_lists_are_forbidden(self, auth_client, user, other_user):
        f.block(other_user, user)
        assert auth_client.get(reverse("load_more_generic", args=["following"]), {"offset": 0, "username": other_user.username}).status_code == 403


class TestLogout:
    def test_logout_needs_a_post(self, auth_client):
        assert auth_client.get(reverse("logout")).status_code == 405
        assert auth_client.get(reverse("account_settings_home")).status_code == 200
        assert auth_client.post(reverse("logout")).status_code == 302


class TestPublicProfile:
    def test_removed_beers_are_not_listed_on_the_first_page(self, auth_client, other_user, beer):
        gone = f.make_beer(name="Disparue", added_by=other_user)
        gone.is_deleted = True
        gone.save()
        html = auth_client.get(reverse("public_profile", args=[other_user.username]), {"tab": "additions"}).content.decode()
        assert beer.name in html and "Disparue" not in html
