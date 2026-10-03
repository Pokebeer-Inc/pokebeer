"""Capture des créations/modifications de contenus publics (signaux)."""
import pytest

from app.models import ModerationEntry
from tests import factories as f

pytestmark = pytest.mark.django_db


def entries(kind=None, action=None):
    qs = ModerationEntry.objects.pending()
    if kind:
        qs = qs.filter(kind=kind)
    if action:
        qs = qs.filter(action=action)
    return qs


class TestCapture:
    def test_new_beer_is_recorded_as_creation(self):
        beer = f.make_beer(name="Brune", description="Douce")
        entry = entries("beer", "created").get(object_id=beer.pk)
        assert {c["field"] for c in entry.changes} >= {"name", "description"}

    def test_modification_records_only_changed_fields_with_old_value(self):
        beer = f.make_beer(name="Blonde", description="Avant")
        beer.description = "Après"
        beer.save()
        entry = entries("beer", "modified").get(object_id=beer.pk)
        assert [(c["field"], c["old"], c["new"]) for c in entry.changes] == [("description", "Avant", "Après")]

    def test_each_new_modification_creates_a_new_entry(self):
        beer = f.make_beer(description="v1")
        for text in ("v2", "v3"):
            beer.description = text
            beer.save()
        assert entries("beer", "modified").count() == 2

    def test_save_without_tracked_change_records_nothing(self):
        beer = f.make_beer()
        before = ModerationEntry.objects.count()
        beer.degree = 9
        beer.save()
        assert ModerationEntry.objects.count() == before

    def test_comment_creation_and_edit(self, user):
        drink = f.make_drink(user, comment="Super")
        assert entries("comment", "created").filter(object_id=drink.pk).exists()
        drink.comment = "Nul"
        drink.save()
        assert entries("comment", "modified").filter(object_id=drink.pk).exists()

    def test_login_style_partial_save_does_not_record(self, user):
        before = ModerationEntry.objects.count()
        user.save(update_fields=["fcm_token"])
        assert ModerationEntry.objects.count() == before

    def test_bio_change_is_recorded_for_users(self, user):
        user.bio = "Salut"
        user.save()
        assert entries("user", "modified").filter(object_id=user.pk).exists()

    def test_brewery_and_bar_are_recorded(self):
        brewery, bar = f.make_brewery(), f.make_bar()
        assert entries("brewery", "created").filter(object_id=brewery.pk).exists()
        assert entries("bar", "created").filter(object_id=bar.pk).exists()

    def test_soft_deleted_beer_drops_its_pending_entries(self):
        beer = f.make_beer()
        beer.is_deleted = True
        beer.save()
        assert not entries("beer").filter(object_id=beer.pk).exists()

    def test_hard_delete_drops_entries(self, user):
        drink = f.make_drink(user)
        drink.delete()
        assert not entries("comment").filter(object_id=drink.pk).exists()

    def test_capture_failure_never_blocks_publication(self, monkeypatch):
        monkeypatch.setattr("app.services.moderation.capture.ModerationEntry.objects.create", lambda **kw: 1 / 0)
        assert f.make_beer(name="Publiée").pk
