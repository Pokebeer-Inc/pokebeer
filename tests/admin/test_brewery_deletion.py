"""Supprimer une brasserie n'efface jamais ses bières ni leurs dégustations sans un choix explicite de l'équipe."""
import pytest
from django.db.models import ProtectedError
from django.urls import reverse

from app.models import Beer, Brewery, Drinks
from app.services.establishments import removal
from tests import factories as f

pytestmark = pytest.mark.django_db


@pytest.fixture
def old(user):
    brewery = f.make_brewery(name="Ancienne")
    f.make_drink(user, f.make_beer(name="Blonde", brewery=brewery))
    return brewery


class TestDatabaseGuard:
    def test_a_brewery_with_beers_cannot_be_deleted_by_accident(self, old):
        with pytest.raises(ProtectedError):
            old.delete()


class TestService:
    def test_transfer_keeps_the_beers_and_the_tastings(self, old):
        target = f.make_brewery(name="Nouvelle")
        removal.delete_brewery(old, transfer_to=target)
        assert not Brewery.objects.filter(pk=old.pk).exists()
        assert Beer.objects.get(name="Blonde").brewery == target and Drinks.objects.count() == 1

    def test_a_homonym_at_the_target_blocks_the_transfer(self, old):
        target = f.make_brewery(name="Nouvelle")
        f.make_beer(name="Blonde", brewery=target)
        with pytest.raises(removal.RemovalError, match="Blonde"):
            removal.delete_brewery(old, transfer_to=target)
        assert Brewery.objects.filter(pk=old.pk).exists()

    def test_explicit_deletion_removes_everything(self, old):
        removal.delete_brewery(old, delete_beers=True)
        assert not Beer.objects.exists() and not Drinks.objects.exists()

    def test_impact(self, old):
        assert removal.impact(old) == {'beers': 1, 'tastings': 1}


class TestAdmin:
    def url(self, brewery):
        return reverse("admin:app_brewery_delete", args=[brewery.pk])

    def test_the_page_asks_what_to_do_with_the_beers(self, admin_client, old):
        html = admin_client.get(self.url(old)).content.decode()
        assert "1 bière" in html and "1 dégustation" in html and 'name="action"' in html

    def test_transfer_from_the_admin(self, admin_client, old):
        target = f.make_brewery(name="Nouvelle")
        response = admin_client.post(self.url(old), {"action": "transfer", "target": target.pk})
        assert response.status_code == 302 and Beer.objects.get(name="Blonde").brewery == target

    def test_deleting_everything_needs_a_confirmation(self, admin_client, old):
        admin_client.post(self.url(old), {"action": "delete"})
        assert Brewery.objects.filter(pk=old.pk).exists()
        admin_client.post(self.url(old), {"action": "delete", "confirm_delete": "on"})
        assert not Brewery.objects.filter(pk=old.pk).exists() and not Drinks.objects.exists()

    def test_an_empty_brewery_uses_the_usual_page(self, admin_client):
        empty = f.make_brewery(name="Vide")
        assert 'name="action"' not in admin_client.get(self.url(empty)).content.decode()
