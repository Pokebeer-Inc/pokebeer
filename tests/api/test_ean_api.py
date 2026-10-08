"""API de recherche par code-barres : catalogue d'abord, puis Open Food Facts, avec quota et protections."""
from unittest import mock

import pytest
from django.urls import reverse

from app.models import Beer
from app.services import product_lookup
from tests import factories as f

pytestmark = pytest.mark.django_db

URL = reverse("lookup_ean")
LEFFE = "5410228142218"
BEER = {"name": "Leffe Blonde", "brewery": "Leffe", "style": None, "degree": 6.6, "bitterness": None}


@pytest.fixture
def off(monkeypatch):
    fetch = mock.Mock(return_value=dict(BEER))
    monkeypatch.setattr(product_lookup, "fetch", fetch)
    return fetch


def lookup(client, code=LEFFE):
    return client.post(URL, {"ean": code})


class TestLookup:
    def test_a_known_product_prefills_the_beer(self, auth_client, off):
        body = lookup(auth_client).json()
        assert body == {"success": True, "source": "openfoodfacts", "ean": LEFFE, "data": BEER}
        off.assert_called_once_with(LEFFE)

    def test_an_upc_a_code_is_normalised_before_the_lookup(self, auth_client, off):
        lookup(auth_client, "012345678905")
        off.assert_called_once_with("0012345678905")

    def test_the_catalogue_is_searched_first_without_calling_the_service_or_using_quota(self, auth_client, off, settings):
        settings.EAN_DAILY_LIMIT = 1
        beer = f.make_beer(name="Déjà là")
        Beer.objects.filter(pk=beer.pk).update(ean=LEFFE)
        for _ in range(3):
            body = lookup(auth_client).json()
            assert body["source"] == "catalog" and body["existing"] == {"name": "Déjà là", "brewery": beer.brewery_id.name, "slug": beer.slug}
        off.assert_not_called()

    def test_deleted_beers_and_blocked_members_beers_are_not_offered(self, auth_client, off, user, other_user):
        gone = f.make_beer(name="Supprimée", is_deleted=True)
        theirs = f.make_beer(name="D'un bloqué", added_by=other_user)
        Beer.objects.filter(pk=gone.pk).update(ean=LEFFE)
        f.block(user, other_user)
        assert lookup(auth_client).json()["source"] == "openfoodfacts"
        Beer.objects.filter(pk=gone.pk).update(ean=None)
        Beer.objects.filter(pk=theirs.pk).update(ean=LEFFE)
        assert lookup(auth_client).json()["source"] == "openfoodfacts"

    def test_an_unknown_code_is_a_normal_answer(self, auth_client, off):
        off.return_value = None
        response = lookup(auth_client)
        assert response.status_code == 200 and response.json()["success"] is False and response.json()["not_found"] is True

    def test_a_service_outage_is_reported_without_details(self, auth_client, off):
        off.side_effect = product_lookup.LookupUnavailable("secret internal detail")
        response = lookup(auth_client)
        assert response.status_code == 503 and "secret" not in response.content.decode()

    @pytest.mark.parametrize("code", ["", "abc", "5410228142219", "../../x", "5410228142218; rm", "1" * 40])
    def test_invalid_codes_never_reach_the_service(self, auth_client, off, code):
        assert lookup(auth_client, code).status_code == 400
        off.assert_not_called()

    def test_missing_code_is_refused(self, auth_client, off):
        assert auth_client.post(URL).status_code == 400

    def test_the_daily_quota_applies_to_external_lookups(self, auth_client, off, settings):
        settings.EAN_DAILY_LIMIT = 2
        assert [lookup(auth_client).status_code for _ in range(3)] == [200, 200, 429]

    def test_the_quota_is_per_member_and_separate_from_other_scopes(self, auth_client, other_client, off, settings):
        settings.EAN_DAILY_LIMIT = 1
        lookup(auth_client)
        assert lookup(auth_client).status_code == 429 and lookup(other_client).status_code == 200

    def test_login_and_post_are_required_and_csrf_is_enforced(self, client, auth_client, off):
        from django.test import Client
        assert client.post(URL, {"ean": LEFFE}).status_code == 302
        assert auth_client.get(URL).status_code == 405
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(f.make_user())
        assert strict.post(URL, {"ean": LEFFE}).status_code == 403
        off.assert_not_called()
