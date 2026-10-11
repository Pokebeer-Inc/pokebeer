"""Une bière qui a un vecteur de recherche (tableau numpy) doit pouvoir être modifiée : formulaire public, modération et administration."""
import numpy as np
import pytest
from django.urls import reverse

from app.models import Beer
from tests import factories as f

pytestmark = pytest.mark.django_db


@pytest.fixture
def embedded_beer(geocoder):
    beer = f.make_beer(name="Avec vecteur")
    Beer.objects.filter(pk=beer.pk).update(embedding=[0.1] * 1024)
    return Beer.objects.get(pk=beer.pk)


def test_the_loaded_vector_is_a_numpy_array(embedded_beer):
    assert isinstance(embedded_beer.embedding, np.ndarray)


def test_validating_the_beer_does_not_trip_on_its_vector(embedded_beer):
    embedded_beer.full_clean()
    embedded_beer.validate_constraints()


def test_constraints_are_still_enforced(embedded_beer):
    from django.core.exceptions import ValidationError
    twin = Beer(name=embedded_beer.name, brewery=embedded_beer.brewery)
    with pytest.raises(ValidationError):
        twin.validate_constraints()


def test_the_administration_saves_a_beer_that_has_a_vector(client_for, superuser, embedded_beer):
    client = client_for(superuser)
    url = reverse("admin:app_beer_change", args=[embedded_beer.pk])
    form = client.get(url).context["adminform"].form
    data = {name: value for name, value in form.initial.items() if name not in ("image", "embedding") and value not in (None, "", False)}
    data.update({"name": embedded_beer.name, "description": "Nouvelle description", "brewery": embedded_beer.brewery_id, "_save": "Enregistrer"})
    response = client.post(url, data)
    assert response.status_code == 302, getattr(response, "context", None) and response.context["adminform"].form.errors
    assert Beer.objects.get(pk=embedded_beer.pk).description == "Nouvelle description"


def test_the_vector_is_not_an_editable_field_of_the_administration(client_for, superuser, embedded_beer):
    form = client_for(superuser).get(reverse("admin:app_beer_change", args=[embedded_beer.pk])).context["adminform"].form
    assert "embedding" not in form.fields


def test_a_member_can_edit_his_beer_even_with_a_vector(auth_client, user, embedded_beer):
    Beer.objects.filter(pk=embedded_beer.pk).update(added_by=user)
    response = auth_client.post(reverse("edit_beer", args=[embedded_beer.slug]), {
        "name": embedded_beer.name, "brewery_name": embedded_beer.brewery.name, "degree": "5", "description": "Modifiée par le membre",
    })
    assert response.status_code == 302
    assert Beer.objects.get(pk=embedded_beer.pk).description == "Modifiée par le membre"
