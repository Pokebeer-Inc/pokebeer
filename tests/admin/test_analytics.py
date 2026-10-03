from datetime import date, timedelta
from unittest import mock

import pytest
from django.urls import reverse

from app.models import UserAchievementState
from app.services.analytics import geo, privacy, series, trophies
from app.services.analytics.geography import classify_spot
from app.services.analytics.periods import Period
from app.services.analytics.registry import PAGES
from tests import factories as f

pytestmark = pytest.mark.django_db


@pytest.fixture
def populated(superuser, geocoder):
    """Quelques membres, bières, dégustations, lieux et établissements répartis dans le temps."""
    members = [f.make_user(username=f.unique("m_")) for _ in range(4)]
    brewery = f.make_brewery(name="Brasserie Test", address="Lyon")
    f.make_bar(name="Bar Test", address="Lyon")
    ipa = f.make_beer(name="IPA 1", brewery=brewery, style="IPA, NEIPA / Hazy", degree=6.5, bitterness=50)
    lager = f.make_beer(name="Lager 1", brewery=brewery, style="Lager", degree=4.8)
    today = date.today()
    for index, member in enumerate(members):
        for offset in (0, 20, 45, 100):
            f.make_drink(member, ipa if index % 2 else lager, note=index + 5, date=today - timedelta(days=offset))
        f.make_spot(member, latitude=48.85, longitude=2.35, date=today - timedelta(days=index))
    members[0].wishlist_beers.add(ipa)
    f.follow(members[0], members[1])
    UserAchievementState.objects.create(user=members[0], achievement_name="Juge", tier_level=2)
    UserAchievementState.objects.create(user=members[1], achievement_name="Juge", tier_level=0)
    return brewery


class TestAccess:
    @pytest.mark.parametrize("page", [p.key for p in PAGES])
    def test_staff_can_open_every_page(self, client_for, staff, populated, page):
        response = client_for(staff).get(reverse("admin_analytics", args=[page]))
        assert response.status_code == 200 and response.context["blocks"] is not None

    @pytest.mark.parametrize("page", [p.key for p in PAGES])
    def test_members_and_anonymous_are_refused(self, client, auth_client, page):
        url = reverse("admin_analytics", args=[page])
        assert "/admin/login/" in client.get(url).url
        assert auth_client.get(url).status_code == 302

    def test_unknown_page_is_404(self, client_for, staff):
        assert client_for(staff).get(reverse("admin_analytics", args=["nope"])).status_code == 404

    def test_read_only(self, client_for, staff):
        assert client_for(staff).post(reverse("admin_analytics", args=["trends"])).status_code == 405

    def test_index_redirects_to_the_first_page(self, client_for, staff):
        assert client_for(staff).get(reverse("admin_analytics_index")).url == reverse("admin_analytics", args=[PAGES[0].key])

    def test_sidebar_entries_are_staff_only(self, settings):
        group = next(g for g in settings.UNFOLD["SIDEBAR"]["navigation"] if g["title"] == "Analytics")
        assert len(group["items"]) == len(PAGES) + 1  # + « Custom »
        non_staff = type("R", (), {"user": type("U", (), {"is_staff": False})()})()
        assert not any(item["permission"](non_staff) for item in group["items"])

    def test_empty_database_never_crashes(self, client_for, staff):
        for page in PAGES:
            assert client_for(staff).get(reverse("admin_analytics", args=[page.key])).status_code == 200


class TestPeriod:
    @pytest.mark.parametrize("params, expected", [
        ({}, (12, "month")), ({"months": "6", "granularity": "week"}, (6, "week")),
        ({"months": "999", "granularity": "year"}, (12, "month")), ({"months": "abc"}, (12, "month")),
        ({"months": "-3"}, (12, "month")), ({"months": "6; DROP TABLE"}, (12, "month")),
    ])
    def test_values_are_whitelisted(self, params, expected):
        period = Period.from_params(params)
        assert (period.months, period.granularity) == expected

    @pytest.mark.parametrize("granularity", ["week", "month"])
    def test_buckets_cover_the_period_without_gaps(self, granularity):
        period = Period(6, granularity)
        buckets = period.buckets()
        assert buckets[0] <= period.start and buckets[-1] <= period.today < period.next_bucket(buckets[-1])
        assert all(period.next_bucket(a) == b for a, b in zip(buckets, buckets[1:]))


class TestSeries:
    def test_linear_trend_and_forecast(self):
        values = [10, 12, 14, 16, 18, 20, 5]  # le dernier point (en cours) est ignoré
        assert series.forecast(values, 2) == [22.0, 24.0]

    def test_no_forecast_without_enough_history(self):
        assert series.forecast([1, 2, 3]) == [] and series.linear_trend([1, 2]) is None

    def test_forecast_never_goes_negative(self):
        assert min(series.forecast([50, 40, 30, 20, 10, 0, 0], 3)) == 0

    def test_moving_average(self):
        assert series.moving_average([3, 6, 9], 2) == [3.0, 4.5, 7.5]

    @pytest.mark.parametrize("current, previous, expected", [(120, 100, 20.0), (50, 100, -50.0), (5, 0, None)])
    def test_growth(self, current, previous, expected):
        assert series.growth(current, previous) == expected

    def test_trend_page_aligns_series_with_zero_filled_buckets(self, populated):
        from app.models import Drinks
        values = series.count_series(Drinks.objects.all(), "date", Period(6, "month"))
        assert len(values) == len(Period(6, "month").buckets()) and sum(values) == 16


class TestPrivacy:
    def test_small_groups_are_never_published(self):
        assert not privacy.is_publishable(privacy.MIN_GROUP_SIZE - 1) and privacy.is_publishable(privacy.MIN_GROUP_SIZE)

    def test_zone_with_too_few_members_is_hidden_from_the_map(self, client_for, staff, geocoder):
        for member in (f.make_user(username=f.unique("m_")) for _ in range(privacy.MIN_GROUP_SIZE - 1)):
            f.make_spot(member, latitude=45.0, longitude=5.0)
        blocks = client_for(staff).get(reverse("admin_analytics", args=["geography"])).context["blocks"]
        spot_points = [p for b in blocks if b.block_type == "map" for p in b.points if p["color"] == "#2563eb"]
        assert spot_points == []

    def test_published_zone_exposes_neither_coordinates_nor_names(self, client_for, staff, populated):
        response = client_for(staff).get(reverse("admin_analytics", args=["geography"]))
        html = response.content.decode()
        point = next(p for b in response.context["blocks"] if b.block_type == "map" for p in b.points if p["color"] == "#2563eb")
        assert (point["lat"], point["lng"]) != (48.85, 2.35)  # centre de case, pas la position exacte
        assert "Spot " not in html

    def test_no_username_or_email_in_any_page(self, client_for, staff, populated):
        from app.models import BeerUser
        members = BeerUser.objects.filter(username__startswith="m_")  # les membres de la fixture `populated`
        for page in PAGES:
            html = client_for(staff).get(reverse("admin_analytics", args=[page.key])).content.decode()
            assert members.exists()
            assert [m.username for m in members if m.username in html or m.email in html] == []


class TestGeo:
    def test_haversine_paris_lyon(self):
        assert 390_000 < geo.haversine_m(48.8566, 2.3522, 45.7640, 4.8357) < 395_000

    def test_cell_is_the_same_for_close_points_only(self):
        assert geo.cell_of(48.851, 2.351) == geo.cell_of(48.859, 2.359) != geo.cell_of(48.95, 2.35)

    @pytest.mark.parametrize("places, expected", [
        ([(48.85, 2.35, "bar")], "Près d'un bar"),
        ([(48.85, 2.35, "brewery")], "Près d'une brasserie"),
        ([], "Zone sans établissement référencé (rural probable)"),
        ([(48.86, 2.36, "bar")] * 7, "Zone dense en établissements (urbain probable)"),
        ([(48.86, 2.36, "bar")], "Zone peu dense (périurbain probable)"),
    ])
    def test_spot_context(self, places, expected):
        assert classify_spot((48.85, 2.35), places) == expected


class TestTrophies:
    @pytest.mark.parametrize("rate, verdict", [(90, "Trop facile ?"), (50, "Équilibré"), (5, "Difficile"), (0.5, "Très difficile ?")])
    def test_difficulty_labels(self, rate, verdict):
        assert trophies.difficulty(rate) == verdict

    def test_rates_use_evaluated_members(self, client_for, staff, populated):
        table = next(b for b in client_for(staff).get(reverse("admin_analytics", args=["trophies"])).context["blocks"] if b.block_type == "table")
        assert table.rows[0][:2] == ["Juge", 50.0]


class TestContent:
    def test_tastes_split_compound_styles(self, client_for, staff, populated):
        chart = next(b for b in client_for(staff).get(reverse("admin_analytics", args=["tastes"])).context["blocks"] if getattr(b, "id", "") == "styles-volume")
        assert {"IPA", "NEIPA / Hazy", "Lager"} <= set(chart.categories)

    def test_recommendations_list_styles_missing_from_the_catalogue(self, client_for, staff, populated):
        other = f.make_brewery(name="Autre Brasserie")
        stout = f.make_beer(name="Stout X", brewery=other, style="Stout")
        for member in (f.make_user(username=f.unique("s_")) for _ in range(6)):
            f.make_drink(member, stout, note=9)
        response = client_for(staff).get(reverse("admin_analytics", args=["places"]), {"brewery": populated.slug})
        gaps = next(b for b in response.context["blocks"] if getattr(b, "id", "") == "gaps")
        assert [row[0] for row in gaps.rows] == ["Stout"]

    def test_free_text_brewery_param_is_only_a_lookup_key(self, client_for, staff, populated):
        response = client_for(staff).get(reverse("admin_analytics", args=["places"]), {"brewery": "'; DROP TABLE x;--" + "a" * 500})
        assert response.status_code == 200

    def test_chart_data_is_embedded_as_json_not_html(self, client_for, staff, geocoder):
        brewery = f.make_brewery(name="x")
        member = f.make_user(username=f.unique("m_"))
        f.make_drink(member, f.make_beer(name="B", brewery=brewery, style="</script><img src=x onerror=alert(1)>"))
        html = client_for(staff).get(reverse("admin_analytics", args=["tastes"])).content.decode()
        assert "<img src=x" not in html


class TestTrends:
    def test_new_beers_are_dated_by_their_first_tasting(self, client_for, staff, populated):
        blocks = client_for(staff).get(reverse("admin_analytics", args=["trends"])).context["blocks"]
        chart = next(b for b in blocks if getattr(b, "id", "") == "trend-beers")
        assert sum(v for v in chart.series[0]["data"] if v) == 2
        assert chart.dashed == [] or chart.dashed == [2]

    def test_kpis_compare_with_the_previous_period(self, client_for, staff, populated):
        blocks = client_for(staff).get(reverse("admin_analytics", args=["trends"])).context["blocks"]
        drinks = next(b for b in blocks if b.block_type == "kpi" and b.label == "Dégustations")
        assert drinks.value == 16 and drinks.delta is None  # rien sur la période précédente : variation non définie
