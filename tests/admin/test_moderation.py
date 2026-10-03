import pytest
from django.contrib.admin.models import DELETION, LogEntry
from django.urls import reverse

from app.models import Bar, Beer, BeerUser, Brewery, Drinks, ModerationEntry, Notification
from tests import factories as f

pytestmark = pytest.mark.django_db


def entries(kind=None, action=None):
    qs = ModerationEntry.objects.pending()
    if kind:
        qs = qs.filter(kind=kind)
    if action:
        qs = qs.filter(action=action)
    return qs


def validate_url(entry):
    return reverse("admin:app_moderationentry_validate", args=[entry.pk])


def remove_url(entry):
    return reverse("admin:app_moderationentry_remove", args=[entry.pk])


class TestValidate:
    def test_validate_hides_entry_without_touching_content(self, client_for, staff, user):
        drink = f.make_drink(user)
        entry = entries("comment").get(object_id=drink.pk)
        client_for(staff).post(validate_url(entry))
        entry.refresh_from_db()
        assert entry.reviewed_by == staff and entry.reviewed_at
        assert Drinks.objects.filter(pk=drink.pk).exists()

    def test_validated_twice_is_refused_cleanly(self, client_for, staff, user):
        entry = entries("comment").get(object_id=f.make_drink(user).pk)
        client = client_for(staff)
        client.post(validate_url(entry))
        first = ModerationEntry.objects.get(pk=entry.pk).reviewed_at
        client.post(validate_url(entry))
        assert ModerationEntry.objects.get(pk=entry.pk).reviewed_at == first

    def test_new_modification_after_validation_is_a_new_entry(self, client_for, staff):
        beer = f.make_beer(description="a")
        client_for(staff).post(validate_url(entries("beer").get(object_id=beer.pk)))
        beer.description = "b"
        beer.save()
        assert entries("beer", "modified").filter(object_id=beer.pk).count() == 1

    def test_superuser_validating_a_new_bar_certifies_it(self, client_for, superuser):
        bar = f.make_bar()
        client_for(superuser).post(validate_url(entries("bar", "created").get(object_id=bar.pk)))
        bar.refresh_from_db()
        assert bar.is_verified and bar.verified_by == superuser and bar.verified_at

    def test_superuser_validating_a_new_brewery_certifies_it(self, client_for, superuser):
        brewery = f.make_brewery()
        client_for(superuser).post(validate_url(entries("brewery", "created").get(object_id=brewery.pk)))
        assert Brewery.objects.get(pk=brewery.pk).is_verified

    def test_staff_cannot_certify(self, client_for, staff):
        bar = f.make_bar()
        entry = entries("bar", "created").get(object_id=bar.pk)
        client_for(staff).post(validate_url(entry))
        assert not Bar.objects.get(pk=bar.pk).is_verified
        assert ModerationEntry.objects.get(pk=entry.pk).reviewed_at is None

    def test_validating_an_establishment_modification_does_not_certify(self, client_for, superuser):
        bar = f.make_bar(description="a")
        bar.description = "b"
        bar.save()
        client_for(superuser).post(validate_url(entries("bar", "modified").get(object_id=bar.pk)))
        assert not Bar.objects.get(pk=bar.pk).is_verified


class TestRemove:
    def post(self, client, entry, reason="abusive", note=""):
        return client.post(remove_url(entry), {"reason": reason, "note": note})

    def test_removing_a_comment_deletes_it_notifies_author_and_logs(self, client_for, staff, user):
        drink = f.make_drink(user, comment="insulte")
        self.post(client_for(staff), entries("comment").get(object_id=drink.pk), note="Merci de rester poli")
        assert not Drinks.objects.filter(pk=drink.pk).exists()
        notif = Notification.objects.get(recipient=user, notif_type="content_removed")
        assert "insultants" in notif.text_content and "rester poli" in notif.text_content
        assert LogEntry.objects.filter(action_flag=DELETION, user=staff).exists()

    def test_removing_a_comment_clears_top_slot(self, client_for, staff, user):
        drink = f.make_drink(user)
        user.top_beer_1 = drink.beer_id
        user.save()
        self.post(client_for(staff), entries("comment").get(object_id=drink.pk))
        user.refresh_from_db()
        assert user.top_beer_1 is None

    def test_removing_a_beer_soft_deletes_and_keeps_ratings(self, client_for, staff, user, other_user):
        beer = f.make_beer(added_by=user)
        drink = f.make_drink(other_user, beer=beer)
        self.post(client_for(staff), entries("beer").get(object_id=beer.pk), reason="spam")
        assert Beer.objects.get(pk=beer.pk).is_deleted and Drinks.objects.filter(pk=drink.pk).exists()
        assert Notification.objects.filter(recipient=user, notif_type="content_removed").exists()

    def test_staff_cannot_remove_an_establishment(self, client_for, staff):
        bar = f.make_bar()
        self.post(client_for(staff), entries("bar").get(object_id=bar.pk))
        assert Bar.objects.filter(pk=bar.pk).exists()

    def test_superuser_removes_brewery_with_cascade_and_notifies_managers(self, client_for, superuser, user):
        brewery = f.make_brewery(managers=[user])
        beer = f.make_beer(brewery=brewery)
        self.post(client_for(superuser), entries("brewery").get(object_id=brewery.pk), reason="dangerous")
        assert not Brewery.objects.filter(pk=brewery.pk).exists() and not Beer.objects.filter(pk=beer.pk).exists()
        assert Notification.objects.filter(recipient=user, notif_type="content_removed").exists()

    def test_removing_a_bio_clears_it_without_a_new_entry(self, client_for, staff, user):
        user.bio = "propos haineux"
        user.save()
        entry = entries("user", "modified").get(object_id=user.pk)
        self.post(client_for(staff), entry)
        user.refresh_from_db()
        assert user.bio == "" and BeerUser.objects.filter(pk=user.pk).exists()
        assert not entries("user", "modified").filter(object_id=user.pk).exists()

    def test_username_only_entry_cannot_be_removed(self, client_for, staff, user):
        entry = entries("user", "created").get(object_id=user.pk)
        self.post(client_for(staff), entry)
        assert BeerUser.objects.filter(pk=user.pk).exists()
        assert not Notification.objects.filter(notif_type="content_removed").exists()

    def test_invalid_reason_or_long_note_is_refused(self, client_for, staff, user):
        drink = f.make_drink(user)
        entry = entries("comment").get(object_id=drink.pk)
        self.post(client_for(staff), entry, reason="nope")
        self.post(client_for(staff), entry, note="x" * 500)
        assert Drinks.objects.filter(pk=drink.pk).exists()

    def test_author_is_not_notified_of_own_removal(self, client_for, staff):
        drink = f.make_drink(staff)
        self.post(client_for(staff), entries("comment").get(object_id=drink.pk))
        assert not Notification.objects.filter(notif_type="content_removed").exists()


class TestAccessAndPage:
    def test_member_cannot_reach_page_or_actions(self, auth_client, user):
        entry = entries("user").get(object_id=user.pk)
        assert auth_client.get(reverse("admin:app_moderationentry_changelist")).status_code == 302
        auth_client.post(validate_url(entry))
        auth_client.post(remove_url(entry), {"reason": "spam"})
        assert ModerationEntry.objects.get(pk=entry.pk).reviewed_at is None

    def test_actions_reject_get(self, client_for, staff, user):
        entry = entries("user").get(object_id=user.pk)
        assert client_for(staff).get(validate_url(entry)).status_code == 405

    def test_page_renders_filters_and_escapes_content(self, client_for, staff, user):
        f.make_drink(user, comment="<script>alert(1)</script>")
        f.make_beer(name="Visible")
        client = client_for(staff)
        response = client.get(reverse("admin:app_moderationentry_changelist"))
        assert response.status_code == 200
        assert b"<script>alert(1)</script>" not in response.content and b"&lt;script&gt;" in response.content
        only = client.get(reverse("admin:app_moderationentry_changelist"), {"kind": "beer", "action": "created"})
        assert b"Visible" in only.content and b"alert(1)" not in only.content

    def test_done_tab_lists_validated_entries(self, client_for, staff):
        beer = f.make_beer(name="Traitée")
        client = client_for(staff)
        client.post(validate_url(entries("beer").get(object_id=beer.pk)))
        url = reverse("admin:app_moderationentry_changelist")
        assert b"Rien &agrave; relire" not in client.get(url, {"state": "done"}).content
        assert b"Valid\xc3\xa9 le" in client.get(url, {"state": "done"}).content
        assert b"Valid\xc3\xa9 le" not in client.get(url).content

    def test_open_redirect_ignored(self, client_for, staff, user):
        entry = entries("user").get(object_id=user.pk)
        response = client_for(staff).post(validate_url(entry), {"next": "https://evil.example/"})
        assert response.url == reverse("admin:app_moderationentry_changelist")

    def test_notification_renders_for_member(self, auth_client, user):
        f.make_notification(user, "content_removed", text_content="Votre avis a été retiré. Motif : Spam.")
        assert b"Motif : Spam" in auth_client.get(reverse("notifications")).content
