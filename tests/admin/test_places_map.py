import json

import pytest
from django.urls import reverse

from app.admin import dashboard_callback
from app.services.places_map import PUBLIC_FIELDS, places_for_map
from tests import factories as f
from tests.admin.test_admin import admin_request

pytestmark = pytest.mark.django_db


class TestPlacesForMap:
    def test_lists_brewery_and_bar_with_the_same_shape(self, geocoder):
        brewery = f.make_brewery(name="Brasserie A", address="Lyon")
        bar = f.make_bar(name="Bar B", address="Paris")
        places = {p["name"]: p for p in places_for_map()}
        assert places["Brasserie A"]["type"] == "brewery" and places["Bar B"]["type"] == "bar"
        assert places["Brasserie A"]["url"] == reverse("brewery_detail", args=[brewery.slug])
        assert places["Bar B"]["url"] == reverse("bar_detail", args=[bar.slug])
        assert places["Bar B"]["type_label"] == "Bar"
        assert set(places["Bar B"]) == set(places["Brasserie A"])

    def test_ungeolocated_places_are_left_out(self, geocoder):
        f.make_bar(name="Sans adresse", address=None)
        assert places_for_map() == []

    def test_private_data_is_never_exposed(self, geocoder, user):
        f.make_bar(address="Paris", siret="73282932000074", managers=[user])
        place = places_for_map()[0]
        assert "siret" not in place and "alice" not in json.dumps(place) and "managers" not in place
        assert set(place) <= {*PUBLIC_FIELDS, "address", "type", "type_label", "url", "managers_count"}

    def test_counts_managers_and_verification(self, geocoder, user, other_user, superuser):
        f.make_brewery(address="Lyon", managers=[user, other_user], is_verified=True, verified_by=superuser)
        place = places_for_map()[0]
        assert place["managers_count"] == 2 and place["is_verified"] and place["verified_at"] is None

    def test_query_count_does_not_grow_with_the_number_of_places(self, geocoder, django_assert_num_queries):
        for _ in range(5):
            f.make_bar(address="Paris")
            f.make_brewery(address="Lyon")
        with django_assert_num_queries(2):
            places_for_map()


class TestDashboardMap:
    def test_context_exposes_places(self, superuser, geocoder):
        f.make_bar(address="Paris")
        assert len(dashboard_callback(admin_request(superuser), {})["places"]) == 1

    def test_page_embeds_data_safely_and_loads_leaflet_with_integrity(self, client_for, superuser, geocoder):
        f.make_bar(name="</script><img src=x onerror=alert(1)>", address="Paris")
        html = client_for(superuser).get(reverse("admin:index")).content.decode()
        assert 'id="places-data"' in html and "<img src=x" not in html
        assert 'integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="' in html
        assert 'integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="' in html

    def test_regular_member_cannot_reach_the_dashboard(self, auth_client):
        assert auth_client.get(reverse("admin:index")).status_code == 302
