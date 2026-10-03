import json

import pytest
from django.test import Client
from django.urls import reverse

from app.models import AnalyticsLayout
from app.services.analytics import layout
from app.services.analytics.blocks import Chart, Kpi, Note, Table
from tests import factories as f

pytestmark = pytest.mark.django_db


def url(page="trends"):
    return reverse("admin_analytics_layout", args=[page])


def save(client, order=(), hidden=(), page="trends", **kwargs):
    return client.post(url(page), data=json.dumps({"order": list(order), "hidden": list(hidden)}), content_type="application/json", **kwargs)


class TestArrange:
    blocks = lambda self: [Kpi("A", 1), Kpi("B", 2), Chart("c1", "C1", "bar", [], []), Table("t1", "T1", [], []), Note("n")]

    def test_default_order_and_notes_apart(self):
        notes, tiles = layout.arrange(self.blocks(), [], [])
        assert [t.block.id for t in tiles] == ["kpi-a", "kpi-b", "c1", "t1"] and len(notes) == 1

    def test_saved_order_comes_first_then_new_blocks_in_default_order(self):
        _, tiles = layout.arrange(self.blocks(), ["t1", "kpi-b"], [])
        assert [t.block.id for t in tiles] == ["t1", "kpi-b", "kpi-a", "c1"]

    def test_hidden_tiles_are_flagged_and_unknown_ids_ignored(self):
        _, tiles = layout.arrange(self.blocks(), ["ghost", "c1"], ["kpi-a", "ghost"])
        assert [(t.block.id, t.hidden) for t in tiles] == [("c1", False), ("kpi-a", True), ("kpi-b", False), ("t1", False)]

    def test_duplicate_ids_are_made_unique(self):
        _, tiles = layout.arrange([Kpi("Même", 1), Kpi("Même", 2)], [], [])
        assert len({t.block.id for t in tiles}) == 2

    def test_kpi_ids_are_stable_and_slug_safe(self):
        assert Kpi("Dégustations par membre actif", 1).id == "kpi-degustations-par-membre-actif"


class TestCleanIds:
    @pytest.mark.parametrize("value", [None, "abc", {"a": 1}, [1], [None], ["UPPER"], ["a b"], ["../x"], ["<script>"], [""], ["-start"], ["a" * 81], ["ok"] * 101])
    def test_invalid_input_is_rejected(self, value):
        assert layout.clean_ids(value) is None

    def test_valid_ids_are_deduplicated_in_order(self):
        assert layout.clean_ids(["b", "a", "b", "kpi-x"]) == ["b", "a", "kpi-x"]


class TestSaveEndpoint:
    def test_layout_is_saved_and_applied_to_the_page(self, client_for, staff):
        client = client_for(staff)
        assert save(client, order=["trend-drinks"], hidden=["kpi-degustations"]).json() == {"ok": True}
        assert save(client, order=["trend-users", "trend-drinks"], hidden=["trend-bars"]).status_code == 200
        response = client.get(reverse("admin_analytics", args=["trends"]))
        tiles = response.context["tiles"]
        assert [t.block.id for t in tiles[:2]] == ["trend-users", "trend-drinks"]
        assert {t.block.id for t in tiles if t.hidden} == {"trend-bars"}
        assert 'data-tile-id="trend-bars"' in response.content.decode()

    def test_layout_is_private_to_each_member(self, client_for, staff, superuser):
        save(client_for(staff), order=["trend-users"])
        assert layout.load(superuser, "trends") == ([], [])
        tiles = client_for(superuser).get(reverse("admin_analytics", args=["trends"])).context["tiles"]
        assert tiles[0].block.id != "trend-users"

    def test_layout_is_per_page(self, client_for, staff):
        save(client_for(staff), order=["trend-users"], page="trends")
        assert layout.load(staff, "tastes") == ([], [])

    def test_empty_layout_resets_to_default(self, client_for, staff):
        client = client_for(staff)
        save(client, order=["trend-users"])
        save(client, order=[], hidden=[])
        assert not AnalyticsLayout.objects.exists()

    def test_one_row_per_member_and_page(self, client_for, staff):
        client = client_for(staff)
        for order in (["a"], ["b"], ["c"]):
            save(client, order=order)
        assert AnalyticsLayout.objects.count() == 1 and layout.load(staff, "trends")[0] == ["c"]

    @pytest.mark.parametrize("body", ['not json', '[]', '{"order": "x", "hidden": []}', '{"order": ["<script>"], "hidden": []}', '{"order": [], "hidden": [1]}', '{}', '"str"'])
    def test_invalid_payloads_are_rejected_without_writing(self, client_for, staff, body):
        response = client_for(staff).post(url(), data=body, content_type="application/json")
        assert response.status_code == 400 and not AnalyticsLayout.objects.exists()

    def test_oversized_body_is_refused(self, client_for, staff):
        response = client_for(staff).post(url(), data=json.dumps({"order": ["a" * 50] * 200, "hidden": []}), content_type="application/json")
        assert response.status_code == 413

    def test_method_and_page_are_checked(self, client_for, staff):
        client = client_for(staff)
        assert client.get(url()).status_code == 405
        assert save(client, page="nope").status_code == 404

    def test_members_and_anonymous_are_refused(self, client, auth_client):
        assert "/admin/login/" in save(client).url
        assert save(auth_client).status_code == 302
        assert not AnalyticsLayout.objects.exists()

    def test_csrf_is_enforced(self, staff):
        client = Client(enforce_csrf_checks=True)
        client.force_login(staff)
        assert save(client).status_code == 403

    def test_a_member_id_in_the_payload_cannot_target_someone_else(self, client_for, staff, superuser):
        payload = {"order": ["x"], "hidden": [], "user": superuser.pk, "user_id": superuser.pk}
        client_for(staff).post(url(), data=json.dumps(payload), content_type="application/json")
        assert not AnalyticsLayout.objects.filter(user=superuser).exists() and AnalyticsLayout.objects.filter(user=staff).exists()

    def test_deleting_the_member_removes_the_layout(self, client_for, staff):
        save(client_for(staff), order=["a"])
        staff.delete()
        assert not AnalyticsLayout.objects.exists()


class TestPageMarkup:
    def test_every_tile_has_controls_and_the_hidden_panel_exists(self, client_for, staff):
        html = client_for(staff).get(reverse("admin_analytics", args=["trends"])).content.decode()
        assert 'id="analytics-hidden-panel"' in html and 'data-action="hide"' in html and 'data-action="top"' in html
        assert 'data-csrf="' in html and 'data-layout-url="' in html

    def test_tile_titles_are_escaped(self, client_for, staff, geocoder):
        brewery = f.make_brewery(name='"><script>alert(1)</script>')
        member = f.make_user(username=f.unique("t_"))
        f.make_drink(member, f.make_beer(name="B", brewery=brewery, style="IPA"))
        html = client_for(staff).get(reverse("admin_analytics", args=["tastes"])).content.decode()
        assert "<script>alert(1)" not in html
