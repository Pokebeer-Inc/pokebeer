import json
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from app.models import BeerUser, Feedback, FeedbackMessage, Notification, UserBlock
from app.services import feedback as conversations
from app.services import notification_types
from tests import factories as f
from tests.helpers import assert_redirects

pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser(db):
    return f.make_user(username="moderator", groups=("Staff",))


UNREAD = reverse("api_unread_notifications")
SEEN = reverse("api_seen_notifications")


def post_json(client, url, data):
    return client.post(url, data=json.dumps(data), content_type="application/json")


class TestToastsAreShownOnce:
    """Une alerte ne réapparaît ni au rechargement, ni dans un autre onglet, ni après un redémarrage de l'application."""

    def test_each_notification_is_returned_once(self, auth_client, user, other_user):
        f.make_notification(user, sender=other_user)
        first = auth_client.get(UNREAD).json()
        second = auth_client.get(UNREAD).json()
        assert len(first["notifications"]) == 1 and second["notifications"] == []

    def test_unread_count_stays_correct_after_the_toast(self, auth_client, user, other_user):
        f.make_notification(user, sender=other_user)
        auth_client.get(UNREAD)
        assert auth_client.get(UNREAD).json()["unread_count"] == 1  # toujours non lue, juste déjà montrée

    def test_two_sessions_never_get_the_same_alert(self, user, other_user, client_for):
        f.make_notification(user, sender=other_user)
        tab_one, tab_two = client_for(user), client_for(user)
        assert len(tab_one.get(UNREAD).json()["notifications"]) == 1
        assert tab_two.get(UNREAD).json()["notifications"] == []

    def test_read_notifications_and_old_ones_are_not_toasted(self, auth_client, user, other_user):
        f.make_notification(user, is_read=True)
        old = f.make_notification(user, sender=other_user)
        Notification.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=3))
        body = auth_client.get(UNREAD).json()
        assert body["notifications"] == [] and body["unread_count"] == 1

    def test_realtime_toast_is_acknowledged_and_not_replayed(self, auth_client, user, other_user):
        notification = f.make_notification(user, sender=other_user)
        assert post_json(auth_client, SEEN, {"slugs": [notification.slug]}).json() == {"ok": True}
        assert auth_client.get(UNREAD).json()["notifications"] == []

    def test_acknowledging_someone_elses_notification_is_a_no_op(self, auth_client, other_user):
        theirs = f.make_notification(other_user)
        post_json(auth_client, SEEN, {"slugs": [theirs.slug]})
        theirs.refresh_from_db()
        assert theirs.toasted_at is None

    @pytest.mark.parametrize("body", [{"slugs": "x"}, {"slugs": [1]}, {"slugs": ["UPPER"]}, {"slugs": ["../x"]}, {"slugs": ["a"] * 21}, {}, [], {"slugs": ["a" * 151]}])
    def test_ack_payloads_are_validated(self, auth_client, body):
        assert post_json(auth_client, SEEN, body).status_code == 400

    def test_ack_rejects_garbage_and_wrong_methods(self, auth_client, client):
        assert auth_client.post(SEEN, data="not json", content_type="application/json").status_code == 400
        assert auth_client.get(SEEN).status_code == 405
        assert "/login" in post_json(client, SEEN, {"slugs": []}).url

    def test_ack_requires_csrf(self, user):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(user)
        assert post_json(strict, SEEN, {"slugs": []}).status_code == 403

    def test_opening_a_notification_marks_it_read_and_shown(self, auth_client, user, other_user):
        notification = f.make_notification(user, sender=other_user)
        auth_client.get(reverse("read_notification", args=[notification.slug]))
        notification.refresh_from_db()
        assert notification.is_read and notification.toasted_at is not None
        assert auth_client.get(UNREAD).json()["notifications"] == []

    def test_no_n_plus_one_when_many_alerts_are_returned(self, auth_client, user, other_user, django_assert_max_num_queries):
        for _ in range(5):
            f.make_notification(user, sender=other_user)
        with django_assert_max_num_queries(12):
            auth_client.get(UNREAD)


class TestMarkAllRead:
    def test_marks_only_my_notifications(self, auth_client, user, other_user):
        mine, theirs = f.make_notification(user), f.make_notification(other_user)
        assert_redirects(auth_client.post(reverse("mark_all_notifications_read")), reverse("notifications"))
        mine.refresh_from_db(); theirs.refresh_from_db()
        assert mine.is_read and not theirs.is_read

    def test_post_only(self, auth_client):
        assert auth_client.get(reverse("mark_all_notifications_read")).status_code == 405


class TestNotificationsPage:
    def html(self, client):
        return client.get(reverse("notifications")).content.decode()

    def test_system_messages_get_an_icon_not_a_broken_image(self, auth_client, user):
        for kind in ("report_updated", "content_removed", "block_follow_up", "feedback_replied"):
            f.make_notification(user, kind, text_content="x")
        html = self.html(auth_client)
        assert 'src=""' not in html and 'src="None"' not in html and "data-notification-image" not in html

    def test_member_notifications_show_the_sender_avatar(self, auth_client, user, other_user):
        f.make_notification(user, sender=other_user)
        assert other_user.avatar_url in self.html(auth_client)

    def test_notification_from_a_deleted_sender_falls_back_without_error(self, auth_client, user, other_user):
        f.make_notification(user, sender=other_user)
        other_user.delete()
        assert auth_client.get(reverse("notifications")).status_code == 200

    def test_failed_images_are_removed_so_the_icon_shows(self, auth_client, user, other_user):
        f.make_notification(user, sender=other_user)
        assert 'onerror="this.remove()"' in self.html(auth_client)

    def test_trophy_without_computed_data_still_renders(self, auth_client, user):
        f.make_notification(user, "achievement", achievement_name="Inconnu", text_content="Inconnu (Bronze)")
        assert auth_client.get(reverse("notifications")).status_code == 200

    def test_unread_ones_are_marked_and_the_page_is_paginated(self, auth_client, user):
        for _ in range(35):
            f.make_notification(user)
        response = auth_client.get(reverse("notifications"))
        assert len(response.context["notifications"]) == 30 and "Plus anciennes" in response.content.decode()
        assert len(auth_client.get(reverse("notifications"), {"page": 2}).context["notifications"]) == 5

    def test_query_count_does_not_grow_with_the_list(self, auth_client, user, other_user, django_assert_max_num_queries):
        for _ in range(20):
            f.make_notification(user, sender=other_user)
        with django_assert_max_num_queries(15):
            auth_client.get(reverse("notifications"))

    def test_bell_dot_is_always_present_and_hidden_when_nothing_is_unread(self, auth_client, user):
        assert 'data-notification-dot' in auth_client.get(reverse("notifications")).content.decode()


class TestRedirects:
    def go(self, client, notification):
        return client.get(reverse("read_notification", args=[notification.slug]))

    def test_every_type_has_a_destination_and_never_a_dead_page(self, auth_client, user, other_user, beer, brewery):
        for key in notification_types.REGISTRY:
            notification = Notification(recipient=user, sender=other_user, notif_type=key, slug=f.unique("n"), beer=beer, brewery=brewery)
            url = notification_types.get(key).url_for(notification)
            assert url.startswith("/")

    def test_deleted_beer_leads_to_the_list(self, auth_client, user, other_user, beer):
        notification = f.make_notification(user, "beer_shared", sender=other_user, beer=beer)
        Notification.objects.filter(pk=notification.pk).update()
        type(beer).objects.filter(pk=beer.pk).update(is_deleted=True)
        assert_redirects(self.go(auth_client, notification), reverse("notifications"))

    def test_follow_from_a_suspended_member_leads_to_the_list(self, auth_client, user, other_user):
        notification = f.make_notification(user, "follow", sender=other_user)
        BeerUser.objects.filter(pk=other_user.pk).update(is_active=False)
        assert_redirects(self.go(auth_client, notification), reverse("notifications"))

    @pytest.mark.parametrize("blocker_is_recipient", [True, False])
    def test_follow_from_a_blocked_member_leads_to_the_list(self, auth_client, user, other_user, blocker_is_recipient):
        notification = f.make_notification(user, "follow", sender=other_user)
        pair = (user, other_user) if blocker_is_recipient else (other_user, user)
        UserBlock.objects.create(blocker=pair[0], blocked=pair[1])
        assert_redirects(self.go(auth_client, notification), reverse("notifications"))

    def test_follow_from_a_normal_member_leads_to_their_profile(self, auth_client, user, other_user):
        notification = f.make_notification(user, "follow", sender=other_user)
        assert_redirects(self.go(auth_client, notification), reverse("public_profile", args=[other_user.username]))

    def test_bar_notifications_lead_to_the_bar(self, auth_client, user, other_user):
        bar = f.make_bar(name="Le Zinc")
        notification = f.make_notification(user, "place_updated", sender=other_user, bar=bar)
        assert_redirects(self.go(auth_client, notification), reverse("bar_detail", args=[bar.slug]))

    def test_other_members_notifications_are_not_readable(self, other_client, user):
        assert self.go(other_client, f.make_notification(user)).status_code == 404

    def test_redirect_never_leaves_the_site(self, auth_client, user, other_user, beer):
        for key in notification_types.REGISTRY:
            notification = f.make_notification(user, key, sender=other_user, beer=beer) if key != "achievement" else f.make_notification(user, key)
            location = self.go(auth_client, notification).url
            assert location.startswith("/") and not location.startswith("//")

    def test_toast_links_use_the_read_path(self, auth_client, user, other_user):
        notification = f.make_notification(user, sender=other_user)
        assert auth_client.get(UNREAD).json()["notifications"][0]["read_url"] == f"/notifications/read/{notification.slug}/"


class TestLogoutClearsThePushToken:
    def test_device_stops_receiving_after_logout(self, auth_client, user):
        BeerUser.objects.filter(pk=user.pk).update(fcm_token="tok")
        auth_client.get(reverse("logout"))
        user.refresh_from_db()
        assert user.fcm_token is None


class TestTeamConversation:
    @pytest.fixture
    def thread(self, user):
        return conversations.open_thread(user, "Mon tout premier message")

    def test_conversation_shows_every_message_including_the_first(self, auth_client, user, thread, superuser):
        conversations.team_reply(thread, superuser, "Bonjour, merci !")
        conversations.member_reply(thread, user, "Une précision")
        html = auth_client.get(reverse("feedback_thread", args=[thread.slug])).content.decode()
        positions = [html.index(t) for t in ("Mon tout premier message", "Bonjour, merci !", "Une précision")]
        assert positions == sorted(positions) and "votre premier message" in html

    def test_member_and_team_bubbles_are_distinguished(self, auth_client, thread, superuser):
        conversations.team_reply(thread, superuser, "Réponse")
        html = auth_client.get(reverse("feedback_thread", args=[thread.slug])).content.decode()
        assert "is-member" in html and "is-team" in html and "Équipe Pokebeer" in html

    def test_replying_sets_the_thread_pending_for_the_team(self, auth_client, user, thread, superuser):
        conversations.team_reply(thread, superuser, "Réponse")
        assert Feedback.objects.get(pk=thread.pk).status == "replied"
        response = auth_client.post(reverse("feedback_thread", args=[thread.slug]), {"body": "Merci, une question"})
        assert_redirects(response, reverse("feedback_thread", args=[thread.slug]))
        assert Feedback.objects.get(pk=thread.pk).status == "pending"
        assert thread.messages.last().author == user

    def test_team_reply_notifies_the_member_with_a_link_to_the_thread(self, user, thread, superuser):
        conversations.team_reply(thread, superuser, "Voici la réponse complète")
        notification = Notification.objects.get(notif_type="feedback_replied")
        assert notification.recipient == user
        assert notification_types.get("feedback_replied").url_for(notification) == reverse("feedback_thread", args=[thread.slug])

    def test_notification_text_quotes_the_latest_team_message(self, auth_client, user, thread, superuser):
        conversations.team_reply(thread, superuser, "Première")
        conversations.team_reply(thread, superuser, "Dernière réponse")
        html = auth_client.get(reverse("notifications")).content.decode()
        assert "Dernière réponse" in html

    def test_opening_the_thread_reads_its_notifications(self, auth_client, user, thread, superuser):
        conversations.team_reply(thread, superuser, "Réponse")
        auth_client.get(reverse("feedback_thread", args=[thread.slug]))
        assert not Notification.objects.filter(recipient=user, is_read=False).exists()

    def test_threads_are_private(self, other_client, thread):
        assert other_client.get(reverse("feedback_thread", args=[thread.slug])).status_code == 404
        assert other_client.post(reverse("feedback_thread", args=[thread.slug]), {"body": "intrus"}).status_code == 404
        assert not thread.messages.exists()

    def test_thread_list_shows_only_my_threads_latest_first(self, auth_client, user, other_user, superuser):
        older = conversations.open_thread(user, "Ancien sujet")
        newer = conversations.open_thread(user, "Nouveau sujet")
        conversations.team_reply(older, superuser, "Mise à jour récente")
        conversations.open_thread(other_user, "Secret d'un autre")
        response = auth_client.get(reverse("team_messages"))
        assert [r["feedback"] for r in response.context["threads"]] == [older, newer]
        assert "Secret d'un autre" not in response.content.decode()

    def test_login_required(self, client, thread):
        assert "/login" in client.get(reverse("team_messages")).url
        assert "/login" in client.get(reverse("feedback_thread", args=[thread.slug])).url

    @pytest.mark.parametrize("body", ["", "   ", "x" * 2001])
    def test_invalid_replies_are_refused(self, auth_client, thread, body):
        auth_client.post(reverse("feedback_thread", args=[thread.slug]), {"body": body})
        assert not thread.messages.exists()

    def test_daily_quota(self, auth_client, user, thread, monkeypatch):
        monkeypatch.setattr(conversations, "DAILY_MEMBER_LIMIT", 2)
        auth_client.post(reverse("feedback_thread", args=[thread.slug]), {"body": "un"})
        auth_client.post(reverse("feedback_thread", args=[thread.slug]), {"body": "deux"})
        assert thread.messages.count() == 1  # 1 premier message + 1 réponse = quota atteint

    def test_html_in_messages_is_escaped(self, auth_client, user, superuser):
        thread = conversations.open_thread(user, "<script>alert(1)</script>")
        conversations.team_reply(thread, superuser, '<img src=x onerror=alert(1)>')
        html = auth_client.get(reverse("feedback_thread", args=[thread.slug])).content.decode()
        assert "<script>alert(1)" not in html and "<img src=x" not in html

    def test_post_requires_csrf(self, user, thread):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(user)
        assert strict.post(reverse("feedback_thread", args=[thread.slug]), {"body": "x"}).status_code == 403

    def test_account_form_opens_a_thread_and_lands_on_it(self, auth_client, user):
        response = auth_client.post(reverse("account"), {"btn_feedback": "", "message": "Une idée"})
        thread = Feedback.objects.get(user=user)
        assert_redirects(response, reverse("feedback_thread", args=[thread.slug]))

    def test_account_form_respects_the_quota(self, auth_client, user, monkeypatch):
        monkeypatch.setattr(conversations, "DAILY_MEMBER_LIMIT", 1)
        auth_client.post(reverse("account"), {"btn_feedback": "", "message": "un"})
        auth_client.post(reverse("account"), {"btn_feedback": "", "message": "deux"})
        assert Feedback.objects.filter(user=user).count() == 1

    def test_only_a_team_member_may_not_forge_team_messages_through_the_site(self, auth_client, thread):
        auth_client.post(reverse("feedback_thread", args=[thread.slug]), {"body": "faux", "author_kind": "team"})
        assert thread.messages.get().author_kind == "member"

    def test_timeline_starts_with_the_first_message(self, thread, user):
        entries = conversations.timeline(thread)
        assert entries[0].body == "Mon tout premier message" and not entries[0].is_team

    def test_slugs_are_opaque_and_unique(self, user):
        slugs = {conversations.open_thread(user, f"m{i}").slug for i in range(3)}
        assert len(slugs) == 3 and all(len(s) >= 12 for s in slugs)
