import json
from datetime import date, timedelta

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from app.models import AnalyticsLayout, AnalyticsTile, AnalyticsView
from app.services.analytics.custom import engine, service
from app.services.analytics.custom.catalog import CATALOG
from app.services.analytics.custom.spec import MAX_LIMIT, MAX_MEASURES, SpecError, validate
from app.services.analytics.periods import Period
from app.services.analytics.privacy import MIN_GROUP_SIZE
from tests import factories as f

pytestmark = pytest.mark.django_db


def spec(**overrides):
    base = {"dataset": "drinks", "dimension": "style", "measures": ["count"], "chart": "bar"}
    return {**base, **overrides}


def tile_post(**overrides):
    data = {"title": "Ma tuile", "dataset": "drinks", "dimension": "style", "measures": ["count"], "chart": "bar", "limit": "10", "sort": "value_desc"}
    return {**data, **overrides}


@pytest.fixture
def my_view(staff):
    return service.create_view(staff, "Ma vue")


@pytest.fixture
def populated(geocoder):
    brewery = f.make_brewery(name="Brasserie C")
    beers = [f.make_beer(name=f"B{i}", brewery=brewery, style=style) for i, style in enumerate(["IPA", "IPA", "Stout"])]
    members = [f.make_user(username=f.unique("c_")) for _ in range(MIN_GROUP_SIZE + 1)]
    for member in members:
        for beer in beers[:2]:
            f.make_drink(member, beer, note=8)
    f.make_drink(members[0], beers[2], note=4)  # le Stout n'a qu'un seul dégustateur
    for member in members:
        f.make_spot(member, date=date.today() - timedelta(days=1))
    return brewery


class TestSpecValidation:
    def test_valid_spec_is_normalised(self):
        result = validate(spec(measures=["count", "count", "avg_note"], limit="5"))
        assert result.measures == ("count", "avg_note") and result.limit == 5

    @pytest.mark.parametrize("overrides", [
        {"dataset": "auth_user"}, {"dataset": None}, {"chart": "pie3d"}, {"chart": None},
        {"measures": []}, {"measures": ["count"] * 0}, {"measures": ["nope"]}, {"measures": "count"}, {"measures": [1]},
        {"measures": ["count", "members", "avg_note", "beers", "x"]},
        {"dimension": "password"}, {"dimension": "__class__"}, {"dimension": ""},
        {"sort": "random()"}, {"limit": 0}, {"limit": MAX_LIMIT + 1}, {"chart": "kpi"}, {"chart": "kpi", "dimension": "", "measures": ["count", "members"]},
        {"chart": "line", "dimension": "style"}, {"chart": "donut", "measures": ["count", "members"]}, {"trend": True},
    ])
    def test_invalid_specs_are_refused(self, overrides):
        with pytest.raises(SpecError):
            validate(spec(**overrides))

    def test_non_dict_is_refused(self):
        for raw in (None, "x", [], 3):
            with pytest.raises(SpecError):
                validate(raw)

    def test_dimension_must_belong_to_the_chosen_dataset(self):
        with pytest.raises(SpecError):
            validate(spec(dataset="spots", dimension="style"))

    def test_kpi_line_and_trend_combinations(self):
        assert validate(spec(chart="kpi", dimension="")).chart == "kpi"
        assert validate(spec(chart="line", dimension="time", trend=True)).trend is True
        with pytest.raises(SpecError):
            validate(spec(chart="line", dimension="time", measures=["count", "members"], trend=True))

    def test_catalog_exposes_no_member_identity(self):
        forbidden = ("username", "email", "password", "fcm", "drinker", "user")
        for dataset in CATALOG.values():
            for dimension in dataset.dimensions.values():
                assert not any(word in dimension.label.lower() for word in forbidden)
        assert MAX_MEASURES == 4


class TestEngine:
    def block(self, **overrides):
        return engine.build_block(1, "T", spec(**overrides), Period(12, "month"))

    def test_bar_by_style_hides_groups_below_the_privacy_threshold(self, populated):
        block = self.block()
        assert block.categories == ["IPA"] and block.series[0]["data"] == [8] and "masqués" in block.subtitle

    def test_kpi(self, populated):
        block = self.block(chart="kpi", dimension="", measures=["members"])
        assert (block.value, block.block_type, block.id) == (MIN_GROUP_SIZE + 1, "kpi", "tile-1")

    def test_time_series_is_aligned_and_zero_filled(self, populated):
        block = self.block(chart="line", dimension="time")
        assert len(block.categories) == len(Period(12, "month").buckets())
        assert sum(block.series[0]["data"]) == (MIN_GROUP_SIZE + 1) * 2 + 1

    def test_trend_adds_moving_average_series(self, populated):
        block = self.block(chart="line", dimension="time", trend=True)
        assert [s["name"] for s in block.series][:2] == ["Dégustations", "Moyenne mobile (3)"]

    def test_fixed_dimensions_have_every_category(self, populated):
        block = self.block(chart="bar", dimension="weekday")
        assert len(block.categories) == 7 and block.categories[0] == "Lundi"

    def test_table_has_a_column_per_measure(self, populated):
        block = self.block(chart="table", measures=["count", "avg_note"])
        assert block.columns == ["Style (tel que saisi)", "Dégustations", "Note moyenne"] and block.rows[0][0] == "IPA"

    def test_limit_and_sort(self, populated):
        for style in ("Lager", "Pils", "Sour"):
            beer = f.make_beer(name=f"X{style}", style=style)
            for _ in range(MIN_GROUP_SIZE):
                f.make_drink(f.make_user(username=f.unique("s_")), beer)
        assert len(self.block(chart="table", limit=2).rows) == 2
        labels = [r[0] for r in self.block(chart="table", sort="label_asc", limit=25).rows]
        assert labels == sorted(labels)

    def test_brewery_filter(self, populated):
        other = f.make_beer(name="Autre", brewery=f.make_brewery(name="Autre B"), style="Pils")
        for _ in range(MIN_GROUP_SIZE):
            f.make_drink(f.make_user(username=f.unique("o_")), other)
        block = engine.build_block(1, "T", spec(chart="table"), Period(), {"brewery": populated.slug})
        assert [r[0] for r in block.rows] == ["IPA"]

    def test_trophies_dataset_ignores_the_period_and_hides_small_groups(self, user):
        from app.models import UserAchievementState
        UserAchievementState.objects.create(user=user, achievement_name="Juge", tier_level=1)
        block = engine.build_block(1, "T", {"dataset": "trophies", "dimension": "trophy", "measures": ["count"], "chart": "table"}, Period())
        assert block.rows == []

    def test_corrupted_spec_in_database_never_raises(self):
        block = engine.build_block(7, "T", {"dataset": "drinks", "dimension": "'; DROP TABLE x;--", "measures": ["count"], "chart": "bar"}, Period())
        assert block.block_type == "table" and block.columns == ["Tuile invalide"]

    def test_query_count_is_bounded(self, populated):
        with CaptureQueriesContext(connection) as queries:
            self.block(chart="table", measures=["count", "members", "avg_note", "beers"])
        assert len(queries) <= 3


class TestService:
    def test_view_names_are_unique_per_member_and_bounded(self, staff, superuser):
        service.create_view(staff, "Vue")
        service.create_view(superuser, "Vue")  # un autre membre peut réutiliser le nom
        with pytest.raises(SpecError):
            service.create_view(staff, "Vue")
        with pytest.raises(SpecError):
            service.create_view(staff, "x" * 81)
        with pytest.raises(SpecError):
            service.create_view(staff, "   ")

    def test_quotas(self, staff, monkeypatch):
        monkeypatch.setattr(service, "MAX_VIEWS", 2)
        monkeypatch.setattr(service, "MAX_TILES", 1)
        view = service.create_view(staff, "A")
        service.create_view(staff, "B")
        with pytest.raises(SpecError):
            service.create_view(staff, "C")
        service.add_tile(view, "T", validate(spec()))
        with pytest.raises(SpecError):
            service.add_tile(view, "T2", validate(spec()))

    def test_deleting_a_view_removes_tiles_and_layout(self, staff, my_view):
        service.add_tile(my_view, "T", validate(spec()))
        AnalyticsLayout.objects.create(user=staff, page_key=service.page_key(my_view), order=["tile-1"])
        service.delete_view(my_view)
        assert not AnalyticsTile.objects.exists() and not AnalyticsLayout.objects.exists()

    def test_control_characters_are_stripped_from_names(self, staff):
        assert service.create_view(staff, "Vue\x00\x1b[31m\n  test").name == "Vue[31m test"


class TestFlow:
    """Parcours complet de l'administrateur."""

    def test_full_creation_flow(self, client_for, staff, populated):
        client = client_for(staff)
        assert client.get(reverse("admin_analytics_custom")).status_code == 200

        response = client.post(reverse("admin_analytics_view_create"), {"name": "Suivi IPA"})
        view = AnalyticsView.objects.get(user=staff)
        assert response.url == reverse("admin_analytics_tile_new", args=[view.pk])

        assert client.get(response.url).status_code == 200
        response = client.post(response.url, tile_post(title="Styles bus"))
        assert response.url == reverse("admin_analytics_view", args=[view.pk])
        tile = view.tiles.get()
        assert tile.title == "Styles bus" and tile.spec["dataset"] == "drinks"

        page = client.get(response.url)
        assert page.status_code == 200 and page.context["tiles"][0].block.id == f"tile-{tile.pk}"
        assert "Styles bus" in page.content.decode()

        response = client.post(reverse("admin_analytics_tile_edit", args=[view.pk, tile.pk]), tile_post(title="Renommée", chart="table"))
        tile.refresh_from_db()
        assert (tile.title, tile.spec["chart"]) == ("Renommée", "table")

        client.post(reverse("admin_analytics_view_rename", args=[view.pk]), {"name": "Autre nom"})
        view.refresh_from_db()
        assert view.name == "Autre nom"

        client.post(reverse("admin_analytics_tile_delete", args=[view.pk, tile.pk]))
        assert not view.tiles.exists()
        client.post(reverse("admin_analytics_view_delete", args=[view.pk]))
        assert not AnalyticsView.objects.exists()

    def test_same_filters_as_other_pages_apply_to_custom_tiles(self, client_for, staff, my_view, populated):
        service.add_tile(my_view, "Série", validate(spec(chart="line", dimension="time")))
        client = client_for(staff)
        wide = client.get(reverse("admin_analytics_view", args=[my_view.pk]), {"months": "24", "granularity": "week"})
        narrow = client.get(reverse("admin_analytics_view", args=[my_view.pk]), {"months": "3"})
        assert len(wide.context["blocks"][0].categories) > len(narrow.context["blocks"][0].categories)
        assert [p["param"] for p in wide.context["pickers"]] == ["brewery"]

    def test_layout_and_export_work_on_custom_views(self, client_for, staff, my_view, populated):
        tile = service.add_tile(my_view, "Série", validate(spec(chart="table")))
        client = client_for(staff)
        key = service.page_key(my_view)
        saved = client.post(reverse("admin_analytics_layout", args=[key]), data=json.dumps({"order": [f"tile-{tile.pk}"], "hidden": []}), content_type="application/json")
        assert saved.status_code == 200 and AnalyticsLayout.objects.filter(user=staff, page_key=key).exists()
        csv_response = client.get(reverse("admin_analytics_view", args=[my_view.pk]), {"export": f"tile-{tile.pk}"})
        assert csv_response["Content-Type"].startswith("text/csv") and b"IPA" in csv_response.content

    def test_invalid_tile_form_is_redisplayed_with_errors(self, client_for, staff, my_view):
        response = client_for(staff).post(reverse("admin_analytics_tile_new", args=[my_view.pk]), tile_post(chart="line", dimension="style"))
        assert response.status_code == 400 and "courbe" in response.content.decode().lower() and not my_view.tiles.exists()

    def test_sidebar_and_nav_expose_custom(self, client_for, staff):
        html = client_for(staff).get(reverse("admin_analytics_custom")).content.decode()
        assert reverse("admin_analytics_custom") in html and "Custom" in html


class TestSecurity:
    PAGES_FOR_VIEW = ["admin_analytics_view", "admin_analytics_view_rename", "admin_analytics_view_delete", "admin_analytics_tile_new"]

    def test_anonymous_and_members_are_refused_everywhere(self, client, auth_client, my_view):
        tile = service.add_tile(my_view, "T", validate(spec()))
        urls = [reverse("admin_analytics_custom"), reverse("admin_analytics_view_create"),
                *(reverse(n, args=[my_view.pk]) for n in self.PAGES_FOR_VIEW),
                reverse("admin_analytics_tile_edit", args=[my_view.pk, tile.pk]), reverse("admin_analytics_tile_delete", args=[my_view.pk, tile.pk])]
        for url in urls:
            assert "/admin/login/" in client.post(url).url
            assert auth_client.post(url).status_code == 302
        assert AnalyticsView.objects.count() == 1 and AnalyticsTile.objects.count() == 1

    def test_other_administrators_views_are_invisible_and_untouchable(self, client_for, superuser, my_view):
        tile = service.add_tile(my_view, "T", validate(spec()))
        intruder = client_for(superuser)
        for name, kwargs in [("admin_analytics_view", {}), ("admin_analytics_tile_new", {})]:
            assert intruder.get(reverse(name, args=[my_view.pk])).status_code == 404
        assert intruder.get(reverse("admin_analytics_tile_edit", args=[my_view.pk, tile.pk])).status_code == 404
        for url in (reverse("admin_analytics_view_rename", args=[my_view.pk]), reverse("admin_analytics_view_delete", args=[my_view.pk]),
                    reverse("admin_analytics_tile_delete", args=[my_view.pk, tile.pk])):
            assert intruder.post(url, {"name": "pwn"}).status_code == 404
        assert intruder.post(reverse("admin_analytics_tile_new", args=[my_view.pk]), tile_post()).status_code == 404
        assert AnalyticsView.objects.get().name == "Ma vue" and AnalyticsTile.objects.count() == 1

    def test_a_tile_cannot_be_edited_through_another_view(self, client_for, staff, my_view):
        other = service.create_view(staff, "Autre")
        tile = service.add_tile(my_view, "T", validate(spec()))
        assert client_for(staff).post(reverse("admin_analytics_tile_edit", args=[other.pk, tile.pk]), tile_post()).status_code == 404

    def test_custom_layout_key_of_someone_else_is_refused(self, client_for, superuser, my_view):
        response = client_for(superuser).post(reverse("admin_analytics_layout", args=[service.page_key(my_view)]),
                                              data=json.dumps({"order": ["a"], "hidden": []}), content_type="application/json")
        assert response.status_code == 404 and not AnalyticsLayout.objects.exists()

    def test_mutations_require_post_and_csrf(self, client_for, staff, my_view):
        client = client_for(staff)
        assert client.get(reverse("admin_analytics_view_delete", args=[my_view.pk])).status_code == 405
        assert client.get(reverse("admin_analytics_view_create")).status_code == 405
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(staff)
        for url in (reverse("admin_analytics_view_delete", args=[my_view.pk]), reverse("admin_analytics_tile_new", args=[my_view.pk])):
            assert strict.post(url, tile_post()).status_code == 403
        assert AnalyticsView.objects.exists()

    def test_forged_owner_or_ids_in_the_form_are_ignored(self, client_for, staff, superuser, my_view):
        client_for(staff).post(reverse("admin_analytics_tile_new", args=[my_view.pk]), {**tile_post(), "view": 999, "user": superuser.pk, "id": 1, "spec": "{}"})
        tile = AnalyticsTile.objects.get()
        assert tile.view == my_view and my_view.user == staff

    @pytest.mark.parametrize("title", ["<script>alert(1)</script>", '"><img src=x onerror=alert(1)>'])
    def test_titles_and_names_are_escaped_on_every_page(self, client_for, staff, my_view, title):
        client = client_for(staff)
        client.post(reverse("admin_analytics_tile_new", args=[my_view.pk]), tile_post(title=title))
        client.post(reverse("admin_analytics_view_rename", args=[my_view.pk]), {"name": title})
        for url in (reverse("admin_analytics_view", args=[my_view.pk]), reverse("admin_analytics_custom"),
                    reverse("admin_analytics_tile_new", args=[my_view.pk])):
            html = client.get(url).content.decode()
            assert "<script>alert(1)" not in html and "<img src=x" not in html

    def test_hostile_values_never_reach_the_orm(self, client_for, staff, my_view):
        for field, value in (("dimension", "beer_id__drinker_id__password"), ("dataset", "BeerUser"), ("measures", "password"), ("sort", "?"), ("limit", "99999999")):
            response = client_for(staff).post(reverse("admin_analytics_tile_new", args=[my_view.pk]), tile_post(**{field: value}))
            assert response.status_code == 400
        assert not AnalyticsTile.objects.exists()

    def test_quota_is_enforced_through_the_ui(self, client_for, staff, monkeypatch):
        monkeypatch.setattr(service, "MAX_VIEWS", 1)
        client = client_for(staff)
        client.post(reverse("admin_analytics_view_create"), {"name": "A"})
        response = client.post(reverse("admin_analytics_view_create"), {"name": "B"})
        assert response.status_code == 400 and AnalyticsView.objects.count() == 1

    def test_no_member_identity_in_custom_output(self, client_for, staff, my_view, populated):
        service.add_tile(my_view, "T", validate(spec(chart="table", dimension="beer", measures=["count", "members"])))
        html = client_for(staff).get(reverse("admin_analytics_view", args=[my_view.pk])).content.decode()
        from app.models import BeerUser
        assert [u.username for u in BeerUser.objects.filter(username__startswith="c_") if u.username in html] == []
