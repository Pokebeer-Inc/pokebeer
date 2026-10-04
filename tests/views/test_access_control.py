"""Contrôles transverses : authentification, méthodes HTTP et protection CSRF de chaque route."""
import pytest
from django.test import Client
from django.urls import reverse

from app.models import Notification, UserFollow
from tests import factories as f
from tests.helpers import assert_redirects_to_login

pytestmark = pytest.mark.django_db

GET, POST = "get", "post"

PROTECTED_ROUTES = [
    ("index", {}, GET),
    ("all_beers", {}, GET),
    ("map", {}, GET),
    ("achievements", {}, GET),
    ("notebook", {}, GET),
    ("create_custom_notebook", {}, POST),
    ("notebook_all", {}, GET),
    ("notebook_detail", {"notebook_slug": "some-slug"}, GET),
    ("delete_custom_notebook", {"notebook_slug": "some-slug"}, POST),
    ("edit_custom_notebook", {"notebook_slug": "some-slug"}, POST),
    ("logout", {}, GET),
    ("account", {}, GET),
    ("delete_account", {}, POST),
    ("update_top_beer", {"slot": 1}, POST),
    ("swap_top_beers", {}, POST),
    ("notifications", {}, GET),
    ("read_notification", {"notif_slug": "some-slug"}, GET),
    ("delete_notification", {"notif_slug": "some-slug"}, POST),
    ("public_profile", {"username": "someone"}, GET),
    ("follow_user", {"username": "someone"}, POST),
    ("remove_follower", {"username": "someone"}, POST),
    ("my_reports", {}, GET),
    ("submit_report", {}, POST),
    ("block_user", {"username": "someone"}, POST),
    ("unblock_user", {"username": "someone"}, POST),
    ("blocked_users", {}, GET),
    ("beer_detail", {"beer_slug": "some-beer"}, GET),
    ("add_beer", {}, GET),
    ("edit_beer", {"beer_slug": "some-beer"}, GET),
    ("delete_beer", {"beer_slug": "some-beer"}, POST),
    ("toggle_wishlist", {"beer_slug": "some-slug"}, POST),
    ("wishlist_view", {}, GET),
    ("brewery_detail", {"brewery_slug": "some-slug"}, GET),
    ("bar_detail", {"bar_slug": "some-slug"}, GET),
    ("edit_brewery", {"brewery_slug": "some-slug"}, GET),
    ("edit_bar", {"bar_slug": "some-slug"}, GET),
    ("add_bar_manager", {"bar_slug": "some-slug"}, POST),
    ("remove_bar_manager", {"bar_slug": "some-bar", "username": "someone"}, POST),
    ("add_brewery_manager", {"brewery_slug": "some-slug"}, POST),
    ("remove_brewery_manager", {"brewery_slug": "some-brewery", "username": "someone"}, POST),
    ("rate_beer", {"beer_slug": "some-slug"}, POST),
    ("modify_rate_beer", {"drink_slug": "some-slug"}, POST),
    ("delete_drink", {"drink_slug": "some-slug"}, POST),
    ("delete_spot", {"spot_slug": "some-slug"}, POST),
    ("toggle_reaction", {"drink_slug": "some-slug"}, POST),
    ("analyze_label", {}, POST),
    ("chat_api", {}, GET),
    ("chat_api", {}, POST),
    ("api_unread_notifications", {}, GET),
    ("load_more_generic", {"item_type": "unrated_beers"}, GET),
    ("api_search_users_for_manager", {"brewery_slug": "some-slug"}, GET),
    ("api_search_users_for_bar_manager", {"bar_slug": "some-slug"}, GET),
    ("api_update_fcm_token", {}, POST),
    ("search_brewery", {}, GET),
    ("search_beer", {}, GET),
]

PUBLIC_ROUTES = [
    ("login", {}),
    ("register", {}),
    ("register_pro", {"pro_type": "bar"}),
    ("register_pro", {"pro_type": "brewery"}),

]

POST_ONLY_ROUTES = [
    ("create_custom_notebook", {}),
    ("delete_custom_notebook", {"notebook_slug": "some-slug"}),
    ("edit_custom_notebook", {"notebook_slug": "some-slug"}),
    ("update_top_beer", {"slot": 1}),
    ("swap_top_beers", {}),
    ("submit_report", {}),
    ("block_user", {"username": "bobby"}),
    ("unblock_user", {"username": "bobby"}),
    ("toggle_wishlist", {"beer_slug": "some-slug"}),
    ("toggle_reaction", {"drink_slug": "some-slug"}),
    ("analyze_label", {}),
    ("api_update_fcm_token", {}),
    ("follow_user", {"username": "bobby"}),
    ("delete_notification", {"notif_slug": "some-slug"}),
]


def route_id(route):
    return route[0]


@pytest.mark.parametrize("name, kwargs, method", PROTECTED_ROUTES, ids=[route_id(r) for r in PROTECTED_ROUTES])
def test_anonymous_visitor_is_sent_to_login(client, name, kwargs, method):
    assert_redirects_to_login(getattr(client, method)(reverse(name, kwargs=kwargs)))


@pytest.mark.parametrize("name, kwargs", PUBLIC_ROUTES, ids=[route_id(r) for r in PUBLIC_ROUTES])
def test_public_routes_are_reachable_anonymously(client, google_app, name, kwargs):
    assert client.get(reverse(name, kwargs=kwargs)).status_code == 200


@pytest.mark.parametrize("name, kwargs", POST_ONLY_ROUTES, ids=[route_id(r) for r in POST_ONLY_ROUTES])
def test_state_changing_api_rejects_get(auth_client, name, kwargs):
    assert auth_client.get(reverse(name, kwargs=kwargs)).status_code == 405


@pytest.mark.parametrize("name, kwargs", POST_ONLY_ROUTES + [("delete_account", {}), ("account", {})],
                         ids=[route_id(r) for r in POST_ONLY_ROUTES] + ["delete_account", "account"])
def test_post_without_csrf_token_is_forbidden(user, name, kwargs):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    assert client.post(reverse(name, kwargs=kwargs)).status_code == 403


def test_cross_site_get_cannot_follow(auth_client, user, other_user):
    auth_client.get(reverse("follow_user", args=[other_user.username]))
    assert not UserFollow.objects.exists()


def test_cross_site_get_cannot_delete_a_notification(auth_client, user):
    notification = f.make_notification(user)
    auth_client.get(reverse("delete_notification", args=[notification.slug]))
    assert Notification.objects.filter(pk=notification.pk).exists()
