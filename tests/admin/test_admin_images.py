"""Les images envoyées depuis l'administration suivent le même chemin que sur le site : validées puis ré-encodées en WebP."""
import pytest
from django import forms
from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from app.admin.images import ProcessedImageAdminMixin, processed_image_form
from app.image_form import ProcessedImageMixin
from app.models import Bar, Beer, BeerUser, Brewery, Drinks
from app.services.official_images import process_official_image
from tests import factories as f

pytestmark = pytest.mark.django_db

MODELS_WITH_IMAGES = [Beer, Brewery, Bar, Drinks, BeerUser]


def brewery_form(**files):
    base = processed_image_form({'image': process_official_image})

    class Form(base):
        class Meta:
            model = Brewery
            fields = ['image']

    return Form


@pytest.mark.parametrize("model", MODELS_WITH_IMAGES)
def test_every_admin_with_an_image_field_reencodes_uploads(model, superuser):
    model_admin = admin.site._registry[model]
    request = RequestFactory().get("/")
    request.user = superuser
    assert isinstance(model_admin, ProcessedImageAdminMixin)
    assert issubclass(model_admin.get_form(request), ProcessedImageMixin)
    assert set(model_admin.image_processors) <= {field.name for field in model._meta.fields}


def test_a_fake_image_is_refused():
    fake = SimpleUploadedFile("x.png", b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", content_type="image/png")
    form = brewery_form()(data={}, files={"image": fake}, instance=Brewery())
    assert not form.is_valid() and "image" in form.errors


def test_a_valid_image_is_stored_as_a_random_webp():
    form = brewery_form()(data={}, files={"image": f.make_image_upload()}, instance=Brewery())
    assert form.is_valid()
    image = form.cleaned_data["image"]
    assert image.read()[8:12] == b"WEBP"


def test_the_remove_checkbox_is_offered():
    assert isinstance(brewery_form()().fields["remove_image"], forms.BooleanField)


@pytest.mark.parametrize("model", ["brewery", "bar", "beer", "drinks", "beeruser"])
def test_admin_add_and_change_pages_render(client, superuser, model):
    client.force_login(superuser)
    assert client.get(f"/admin/app/{model}/add/").status_code == 200
