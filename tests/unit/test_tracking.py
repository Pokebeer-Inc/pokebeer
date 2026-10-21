"""Mesures d'usage : vues des fiches, jours d'activité, demandes sans résultat, purge."""
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from app.models import ActivityDay, CatalogMiss, PageView, PageViewVisitor
from app.services.tracking import counters, misses, page_views, retention
from tests import factories as f

pytestmark = pytest.mark.django_db


class TestIncrement:
    def test_creates_then_increments(self):
        lookup = {"kind": "beer", "object_id": 1, "day": timezone.localdate()}
        counters.increment(PageView, lookup, views=1, visitors=1)
        counters.increment(PageView, lookup, views=1)
        row = PageView.objects.get(**lookup)
        assert (row.views, row.visitors) == (2, 1) and PageView.objects.count() == 1

    def test_falls_back_to_update_when_another_request_created_the_row_first(self, monkeypatch):
        lookup = {"kind": "beer", "object_id": 7, "day": timezone.localdate()}
        calls = []
        real_filter = PageView.objects.filter

        def racing_filter(**kwargs):
            if not calls:  # le premier UPDATE ne trouve rien : l'autre requête n'a pas encore créé la ligne...
                calls.append(1)
                PageView.objects.create(**lookup, views=5)  # ...puis elle la crée avant notre INSERT
                return PageView.objects.none()
            return real_filter(**kwargs)

        monkeypatch.setattr(PageView.objects, "filter", racing_filter)
        counters.increment(PageView, lookup, views=1)
        monkeypatch.undo()
        assert PageView.objects.get(**lookup).views == 6


class TestPageViews:
    def test_beer_page_counts_views_and_distinct_visitors(self, auth_client, other_client, beer):
        url = reverse("beer_detail", args=[beer.slug])
        auth_client.get(url), auth_client.get(url), other_client.get(url)
        row = PageView.objects.get(kind="beer", object_id=beer.pk)
        assert (row.views, row.visitors) == (3, 2)

    @pytest.mark.parametrize("name, kind", [("brewery_detail", "brewery"), ("bar_detail", "bar")])
    def test_places_are_counted(self, auth_client, brewery, name, kind):
        place = brewery if kind == "brewery" else f.make_bar(name="Le Zinc", address="Lyon")
        auth_client.get(reverse(name, args=[place.slug]))
        assert PageView.objects.get(kind=kind, object_id=place.pk).views == 1

    def test_staff_and_managers_are_never_counted(self, client_for, staff, superuser, beer, brewery):
        manager = f.make_user(username=f.unique("boss_"))
        brewery.managers.add(manager)
        for member in (staff, superuser, manager):
            client_for(member).get(reverse("beer_detail", args=[beer.slug]))
            client_for(member).get(reverse("brewery_detail", args=[brewery.slug]))
        assert not PageView.objects.exists() and not PageViewVisitor.objects.exists()

    def test_only_get_requests_count(self, rf, user, beer):
        request = rf.post("/")
        request.user = user
        page_views.record(request, page_views.BEER, beer)
        assert not PageView.objects.exists()

    def test_visitor_fingerprint_is_neither_the_member_nor_shared_between_pages(self, auth_client, user, beer, brewery):
        auth_client.get(reverse("beer_detail", args=[beer.slug]))
        auth_client.get(reverse("brewery_detail", args=[brewery.slug]))
        digests = list(PageViewVisitor.objects.values_list("digest", flat=True))
        assert len(set(digests)) == 2 and all(len(d) == 64 and str(user.pk) != d and user.username not in d for d in digests)

    def test_a_failing_measure_never_breaks_the_page(self, auth_client, beer, monkeypatch):
        monkeypatch.setattr(page_views, "increment", lambda *a, **k: 1 / 0)
        assert auth_client.get(reverse("beer_detail", args=[beer.slug])).status_code == 200

    def test_visitor_fingerprints_are_purged_but_counters_stay(self, auth_client, beer):
        auth_client.get(reverse("beer_detail", args=[beer.slug]))
        PageViewVisitor.objects.update(day=timezone.localdate() - timedelta(days=1))
        assert page_views.purge_visitors() == 1 and PageView.objects.count() == 1

    def test_today_fingerprints_are_kept(self, auth_client, beer):
        auth_client.get(reverse("beer_detail", args=[beer.slug]))
        assert page_views.purge_visitors() == 0


class TestActivity:
    def test_first_visit_of_the_day_writes_once(self, auth_client, user):
        auth_client.get(reverse("index"))
        assert ActivityDay.objects.filter(user=user).count() == 1
        with CaptureQueriesContext(connection) as queries:
            auth_client.get(reverse("index"))
        assert not [q for q in queries if "app_activityday" in q["sql"]]  # la session retient le jour : aucune requête de plus

    def test_a_new_day_adds_a_row(self, auth_client, user, monkeypatch):
        auth_client.get(reverse("index"))
        tomorrow = timezone.localdate() + timedelta(days=1)
        monkeypatch.setattr(timezone, "localdate", lambda: tomorrow)
        auth_client.get(reverse("index"))
        assert list(ActivityDay.objects.filter(user=user).order_by("day").values_list("day", flat=True))[-1] == tomorrow
        assert ActivityDay.objects.filter(user=user).count() == 2

    def test_two_sessions_the_same_day_never_duplicate(self, client_for, user):
        client_for(user).get(reverse("index"))
        client_for(user).get(reverse("index"))
        assert ActivityDay.objects.filter(user=user).count() == 1

    def test_anonymous_visitors_leave_nothing(self, client, google_app):
        client.get(reverse("login"))
        assert not ActivityDay.objects.exists()

    def test_rows_disappear_with_the_account(self, user):
        ActivityDay.objects.create(user=user)
        user.delete()
        assert not ActivityDay.objects.exists()


class TestMisses:
    @pytest.mark.parametrize("term, expected", [
        ("  Blonde   SANS gluten ", "blonde sans gluten"), ("Été", "ete"), ("ab", None), ("x" * 61, None),
        ("jean@example.test", None), ("0612345678", None), ("ipa 2024", "ipa 2024"),
    ])
    def test_terms_are_normalised_and_personal_looking_ones_dropped(self, term, expected):
        assert misses.clean_term(term) == expected

    def test_counts_per_source_term_and_day(self):
        for _ in range(3):
            misses.record_search("beers", "Gose framboise")
        misses.record_search("breweries", "Gose framboise")
        assert CatalogMiss.objects.get(source="beer_search", key="gose framboise").count == 3
        assert CatalogMiss.objects.count() == 2

    def test_members_tab_is_never_recorded(self):
        misses.record_search("members", "marie dupont")
        assert not CatalogMiss.objects.exists()

    def test_empty_search_is_recorded_but_found_one_is_not(self, auth_client, beer):
        auth_client.get(reverse("all_beers"), {"q": "zzzintrouvable"})
        auth_client.get(reverse("all_beers"), {"q": beer.name})
        assert list(CatalogMiss.objects.values_list("key", flat=True)) == ["zzzintrouvable"]

    def test_filtered_search_is_not_recorded(self, auth_client):
        auth_client.get(reverse("all_beers"), {"q": "zzzintrouvable", "style": "IPA"})
        assert not CatalogMiss.objects.exists()

    def test_unknown_barcode_is_recorded(self, auth_client, monkeypatch):
        monkeypatch.setattr("app.services.catalog.product_lookup.fetch", lambda code: None)
        auth_client.post(reverse("lookup_ean"), {"ean": "3017620422003"})
        assert CatalogMiss.objects.get(source="ean").key == "3017620422003"

    def test_no_member_is_stored_with_a_miss(self):
        assert {field.name for field in CatalogMiss._meta.get_fields()} == {"id", "source", "key", "day", "count"}


class TestRetention:
    def test_each_measure_has_its_own_deadline(self, user):
        today = timezone.localdate()
        old, recent = today - timedelta(days=retention.ACTIVITY_DAYS + 1), today - timedelta(days=10)
        ActivityDay.objects.create(user=user, day=old), ActivityDay.objects.create(user=user, day=recent)
        CatalogMiss.objects.create(source="ean", key="1", day=today - timedelta(days=retention.MISS_DAYS + 1), count=1)
        CatalogMiss.objects.create(source="ean", key="2", day=recent, count=1)
        PageView.objects.create(kind="beer", object_id=1, day=today - timedelta(days=retention.VIEW_DAYS + 1), views=1)
        result = retention.purge_expired()
        assert result == {"visitors": 0, "views": 1, "activity": 1, "misses": 1}
        assert ActivityDay.objects.get().day == recent and CatalogMiss.objects.get().key == "2"
