import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from app.models import Drinks
from app.services import tasting_photos as tp
from tests import factories as f
from tests.helpers import messages_of

pytestmark = pytest.mark.django_db


def rating(**overrides):
    return {"date": "2026-02-01", "note": "8", "comment": "Bonne mousse", **overrides}


def rate(client, beer, **data):
    return client.post(reverse("rate_beer", args=[beer.slug]), rating(**data))


def modify(client, drink, **data):
    return client.post(reverse("modify_rate_beer", args=[drink.slug]), rating(**data))


class TestRatingWithPhoto:
    def test_photo_is_optional(self, auth_client, user, beer):
        rate(auth_client, beer)
        assert not Drinks.objects.get().photo and Drinks.objects.get().photo_url is None

    def test_photo_is_stored_as_webp_in_the_tastings_folder(self, auth_client, user, beer):
        rate(auth_client, beer, photo=f.make_image_upload())
        drink = Drinks.objects.get()
        assert drink.photo.name.startswith("tastings/") and drink.photo.name.endswith(".webp")
        assert drink.photo_url == drink.photo.url

    def test_invalid_file_refuses_the_rating_and_explains_why(self, auth_client, beer):
        response = rate(auth_client, beer, photo=SimpleUploadedFile("a.png", b"not an image"))
        assert not Drinks.objects.exists() and messages_of(response)

    def test_daily_quota_is_enforced(self, auth_client, beer, monkeypatch):
        monkeypatch.setattr("app.forms.DAILY_LIMIT", 0)
        rate(auth_client, beer, photo=f.make_image_upload())
        assert not Drinks.objects.exists()


class TestModifyPhoto:
    def test_photo_can_be_added_replaced_and_removed(self, auth_client, user, beer, django_capture_on_commit_callbacks):
        drink = f.make_drink(user, beer)
        modify(auth_client, drink, photo=f.make_image_upload())
        drink.refresh_from_db()
        first = drink.photo.name
        assert first

        with django_capture_on_commit_callbacks(execute=True):
            modify(auth_client, drink, photo=f.make_image_upload())
        drink.refresh_from_db()
        assert drink.photo.name != first and not drink.photo.storage.exists(first)

        second = drink.photo.name
        with django_capture_on_commit_callbacks(execute=True):
            modify(auth_client, drink, remove_photo="on")
        drink.refresh_from_db()
        assert not drink.photo and not drink.photo.storage.exists(second)

    def test_photo_is_kept_when_the_form_sends_none(self, auth_client, user, beer):
        drink = f.make_drink(user, beer)
        modify(auth_client, drink, photo=f.make_image_upload())
        drink.refresh_from_db()
        name = drink.photo.name
        modify(auth_client, drink, comment="Nouveau commentaire")
        drink.refresh_from_db()
        assert drink.photo.name == name and drink.comment == "Nouveau commentaire"

    def test_cannot_change_someone_else_photo(self, other_client, user, beer):
        drink = f.make_drink(user, beer)
        assert modify(other_client, drink, photo=f.make_image_upload()).status_code == 404
        drink.refresh_from_db()
        assert not drink.photo


class TestPhotoCleanup:
    def test_file_is_deleted_with_the_drink(self, auth_client, user, beer, django_capture_on_commit_callbacks):
        drink = f.make_drink(user, beer)
        modify(auth_client, drink, photo=f.make_image_upload())
        drink.refresh_from_db()
        name, storage = drink.photo.name, drink.photo.storage
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(reverse("delete_drink", args=[drink.slug]))
        assert not storage.exists(name)


class TestPhotoDisplay:
    def test_photo_is_shown_on_the_beer_page_and_the_public_profile(self, auth_client, user, other_user, beer):
        drink = f.make_drink(other_user, beer)
        drink.photo.save("x.webp", tp.process_tasting_photo(f.make_image_upload()))
        for url in (reverse("beer_detail", args=[beer.slug]), reverse("public_profile", args=[other_user.username])):
            assert drink.photo.url in auth_client.get(url).content.decode()

    def test_own_photo_is_shown_in_the_notebook_with_the_edit_field(self, auth_client, user, beer):
        drink = f.make_drink(user, beer)
        drink.photo.save("x.webp", tp.process_tasting_photo(f.make_image_upload()))
        content = auth_client.get(reverse("notebook_all")).content.decode()
        assert content.count(drink.photo.url) >= 2 and "remove_photo" in content


class TestQuotaOnlyConsumedByValidForms:
    def test_a_rejected_form_does_not_cost_an_upload(self, auth_client, user, beer, monkeypatch):
        from app.models import ChatUsage
        rate(auth_client, beer, comment="", photo=f.make_image_upload())  # commentaire manquant : formulaire invalide
        assert not ChatUsage.objects.filter(user=user, scope=tp.QUOTA_SCOPE).exists()
        rate(auth_client, beer, photo=f.make_image_upload())
        assert ChatUsage.objects.get(user=user, scope=tp.QUOTA_SCOPE).count == 1
