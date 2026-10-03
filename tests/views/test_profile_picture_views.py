import pytest
from django.urls import reverse

from app.models import BeerUser, ModerationEntry
from tests import factories as f
from tests.helpers import assert_redirects, messages_of

pytestmark = pytest.mark.django_db
URL = "update_profile_picture"


def post(client, **files):
    return client.post(reverse(URL), files or {"avatar": f.make_image_upload()})


class TestUpdateProfilePicture:
    def test_login_and_post_are_required(self, client, auth_client):
        assert client.post(reverse(URL)).status_code == 302 and "/login" in client.post(reverse(URL)).url
        assert auth_client.get(reverse(URL)).status_code == 405

    def test_valid_image_is_stored_as_webp(self, auth_client, user):
        assert_redirects(post(auth_client), reverse("account"))
        user.refresh_from_db()
        assert user.avatar.name.endswith(".webp") and user.avatar_url == user.avatar.url

    def test_old_file_is_deleted_when_replaced(self, auth_client, user, django_capture_on_commit_callbacks):
        post(auth_client)
        user.refresh_from_db()
        old = user.avatar.name
        BeerUser.objects.filter(pk=user.pk).update(avatar_updated_at=None)
        with django_capture_on_commit_callbacks(execute=True):
            post(auth_client)
        user.refresh_from_db()
        assert user.avatar.name != old and not user.avatar.storage.exists(old)

    def test_invalid_file_is_refused_and_does_not_start_the_cooldown(self, auth_client, user):
        bad = f.make_image_upload()
        bad.seek(0)
        response = auth_client.post(reverse(URL), {"avatar": type(bad)("a.png", b"not an image")})
        user.refresh_from_db()
        assert not user.avatar and user.avatar_updated_at is None
        assert messages_of(response)

    def test_cooldown_blocks_a_second_upload(self, auth_client, user):
        post(auth_client)
        user.refresh_from_db()
        first = user.avatar.name
        post(auth_client)
        user.refresh_from_db()
        assert user.avatar.name == first

    def test_only_the_photo_is_written(self, auth_client, user):
        BeerUser.objects.filter(pk=user.pk).update(bio="avant")
        auth_client.post(reverse(URL), {"avatar": f.make_image_upload(), "bio": "piraté", "is_superuser": "on", "username": "hacker"})
        user.refresh_from_db()
        assert (user.bio, user.username, user.is_superuser) == ("avant", "alice", False)

    def test_no_identifier_can_target_another_member(self, auth_client, other_user):
        auth_client.post(reverse(URL), {"avatar": f.make_image_upload(), "id": other_user.pk, "user": other_user.pk})
        other_user.refresh_from_db()
        assert not other_user.avatar

    def test_account_page_shows_the_pen(self, auth_client):
        html = auth_client.get(reverse("account")).content.decode()
        assert reverse(URL) in html and 'name="avatar"' in html


class TestModeration:
    @pytest.fixture
    def staff(self):
        return f.make_user(username="moderator", groups=("Staff",))

    def entry(self, user):
        return ModerationEntry.objects.pending().filter(kind="user", object_id=user.pk, action="modified")

    def test_a_new_photo_appears_in_the_moderation_queue(self, auth_client, user):
        post(auth_client)
        change = self.entry(user).get().changes[0]
        assert (change["field"], change["image"]) == ("avatar", True) and change["new"]

    def test_staff_can_remove_the_photo_only(self, client_for, auth_client, user, staff):
        BeerUser.objects.filter(pk=user.pk).update(bio="ma bio")
        post(auth_client)
        entry = self.entry(user).get()
        response = client_for(staff).post(reverse("admin:app_moderationentry_remove", args=[entry.pk]), {"reason": "inappropriate", "note": ""})
        user.refresh_from_db()
        assert response.status_code in (200, 302) and not user.avatar and user.bio == "ma bio"
        assert "photo de profil" in user.notifications.get(notif_type="content_removed").text_content


def test_deleting_the_account_removes_the_stored_photo(auth_client, user, django_capture_on_commit_callbacks):
    post(auth_client)
    user.refresh_from_db()
    name, storage = user.avatar.name, user.avatar.storage
    with django_capture_on_commit_callbacks(execute=True):
        user.delete()
    assert not storage.exists(name)
