"""Slugs publics : génération non énumérable, immuabilité et couverture de tous les modèles exposés."""
import re

import pytest
from django import forms
from django.db import IntegrityError, transaction

from app.models import Bar, Beer, BeerSpot, Brewery, CustomNotebook, Drinks, Notification, Report
from app.services.slugs import SUFFIX_LENGTH, TOKEN_ALPHABET, TOKEN_LENGTH, generate_slug, generate_token
from tests import factories as f

TOKEN = rf"[a-z0-9]{{{TOKEN_LENGTH}}}"


class TestGenerateToken:
    def test_has_the_requested_length_and_alphabet(self):
        token = generate_token()
        assert len(token) == TOKEN_LENGTH and set(token) <= set(TOKEN_ALPHABET)

    def test_is_not_predictable(self):
        assert len({generate_token() for _ in range(1000)}) == 1000

    def test_is_drawn_from_the_system_csprng(self, monkeypatch):
        calls = []
        monkeypatch.setattr("app.services.slugs.secrets.choice", lambda alphabet: calls.append(alphabet) or "a")
        assert generate_token(5) == "aaaaa" and len(calls) == 5


class TestGenerateSlug:
    def test_keeps_a_readable_ascii_prefix(self):
        assert re.fullmatch(rf"punk-ipa-{TOKEN}", generate_slug("Pünk I.P.A"))

    @pytest.mark.parametrize("label", ["", "!!!", "🍺🍺"])
    def test_falls_back_to_the_bare_token(self, label):
        assert re.fullmatch(TOKEN, generate_slug(label))

    def test_never_exceeds_the_maximum_length(self):
        slug = generate_slug("x" * 500, max_length=150)
        assert len(slug) == 150 and re.fullmatch(rf"x+-{TOKEN}", slug)

    def test_truncation_never_leaves_a_dangling_hyphen(self):
        slug = generate_slug("a" * (150 - SUFFIX_LENGTH - 1) + "-b" * 5, max_length=150)
        assert "--" not in slug and re.fullmatch(rf"[a-z0-9-]+-{TOKEN}", slug)


@pytest.mark.django_db
class TestPublicSlugField:
    @pytest.mark.parametrize("make", [f.make_brewery, f.make_bar, f.make_beer])
    def test_public_content_gets_a_readable_slug(self, make):
        assert re.fullmatch(rf"[a-z0-9-]+-{TOKEN}", make().slug)

    def test_private_content_gets_an_opaque_slug_that_hides_its_title(self, user):
        notebook = f.make_notebook(user, title="Mes bières secrètes")
        spot = f.make_spot(user, title="Cachette")
        assert re.fullmatch(TOKEN, notebook.slug) and re.fullmatch(TOKEN, spot.slug)

    @pytest.mark.parametrize("factory", [
        lambda u: f.make_drink(u), lambda u: f.make_notification(u), lambda u: f.make_report(u),
    ])
    def test_other_private_models_get_an_opaque_slug(self, user, factory):
        assert re.fullmatch(TOKEN, factory(user).slug)

    def test_slug_is_generated_by_bulk_create(self, user):
        beers = Beer.objects.bulk_create([Beer(name=f"Bulk {i}", brewery_id=f.make_brewery(), degree=5) for i in range(3)])
        assert len({beer.slug for beer in beers}) == 3 and all(beer.slug for beer in beers)

    def test_slug_never_changes_once_created(self, user):
        drink = f.make_drink(user)
        slug = drink.slug
        drink.note = 1
        drink.save()
        assert Drinks.objects.get(pk=drink.pk).slug == slug

    def test_an_explicit_slug_is_kept(self):
        assert f.make_brewery(slug="chosen-slug").slug == "chosen-slug"

    def test_slug_is_unique_in_database(self):
        first = f.make_brewery()
        with pytest.raises(IntegrityError), transaction.atomic():
            f.make_brewery(slug=first.slug)

    def test_slug_is_not_editable_through_forms(self):
        class BeerSlugForm(forms.ModelForm):
            class Meta:
                model = Beer
                fields = "__all__"

        assert "slug" not in BeerSlugForm().fields

    @pytest.mark.parametrize("model", [Bar, Beer, BeerSpot, Brewery, CustomNotebook, Drinks, Notification, Report])
    def test_every_exposed_model_has_a_required_unique_slug(self, model):
        field = model._meta.get_field("slug")
        assert field.unique and not field.null and not field.editable
