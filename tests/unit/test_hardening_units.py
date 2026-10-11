"""Durcissement : rôles lus une fois, trophées par identifiant stable, sessions glissantes, tâche planifiée, tirage aléatoire sans tri."""
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.contrib.sessions.models import Session
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from app.models import Notification, UserAchievementState
from app.services.members import achievements, inactivity
from app.services.assistant import ai
from app.services.members.visibility import exclude_blocked, exclude_hidden_users
from tests import factories as f

pytestmark = pytest.mark.django_db


class TestRolesAreReadOnce:
    def test_testing_several_roles_costs_one_query(self, user):
        user = type(user).objects.get(pk=user.pk)
        with CaptureQueriesContext(connection) as queries:
            for _ in range(5):
                user.is_staff, user.is_brewer, user.is_bartender, user.primary_role_badge
        assert len(queries) == 1

    def test_changing_the_groups_forgets_the_cache(self, user):
        assert not user.is_staff
        user.groups.add(Group.objects.get_or_create(name="Staff")[0])
        assert user.is_staff
        user.groups.clear()
        assert not user.is_staff

    def test_refreshing_the_member_forgets_the_cache(self, user):
        assert not user.is_brewer
        user.groups.through.objects.create(beeruser_id=user.pk, group=Group.objects.get_or_create(name="Brasseur")[0])
        assert not user.is_brewer  # même instance : valeur lue une fois
        user.refresh_from_db()
        assert user.is_brewer

    def test_prefetched_groups_are_used_without_another_query(self, user):
        member = type(user).objects.prefetch_related("groups").get(pk=user.pk)
        with CaptureQueriesContext(connection) as queries:
            member.is_staff, member.is_brewer
        assert len(queries) == 0


class TestVisibilityHelpers:
    def test_blocking_is_filtered_in_sql_in_both_directions(self, user, other_user, beer):
        mine = f.make_beer(added_by=user)
        f.block(other_user, user)
        from app.models import Beer
        assert set(exclude_blocked(Beer.objects.all(), user, "added_by")) == {mine}

    def test_suspended_members_are_hidden_by_the_stricter_helper(self, user, other_user, beer):
        from app.models import BeerUser, Drinks
        drink = f.make_drink(other_user, beer)
        assert list(exclude_hidden_users(Drinks.objects.all(), user, "drinker")) == [drink]
        BeerUser.objects.filter(pk=other_user.pk).update(is_active=False)
        assert list(exclude_hidden_users(Drinks.objects.all(), user, "drinker")) == []

    def test_an_anonymous_visitor_is_not_filtered(self, beer):
        from django.contrib.auth.models import AnonymousUser
        from app.models import Beer
        assert list(exclude_blocked(Beer.objects.all(), AnonymousUser(), "added_by")) == [beer]


class TestAchievementIdentifiers:
    def test_every_trophy_has_its_display_name_declared(self, user):
        built, _ = achievements.get_user_achievements(user)
        assert {a["slug"]: a["name"] for a in built} == achievements.ACHIEVEMENT_NAMES

    def test_progress_is_stored_by_slug_not_by_name(self, user):
        for _ in range(5):
            f.make_drink(user)
        achievements.check_and_notify_achievements(user)
        assert UserAchievementState.objects.get(user=user, achievement_slug="juge").tier_level == 1
        assert Notification.objects.get(notif_type="achievement").achievement_slug == "juge"

    def test_a_second_computation_does_not_duplicate_states_or_notifications(self, user):
        for _ in range(5):
            f.make_drink(user)
        for _ in range(3):
            achievements.check_and_notify_achievements(user)
        assert UserAchievementState.objects.filter(user=user).count() == len(achievements.ACHIEVEMENT_NAMES)
        assert Notification.objects.filter(notif_type="achievement").count() == 1

    def test_a_tasting_summary_costs_a_fixed_small_number_of_queries(self, user):
        for _ in range(6):
            f.make_drink(user)
        with CaptureQueriesContext(connection) as queries:
            achievements.get_user_achievements(user)
        assert len(queries) <= 7


class TestSessions:
    def test_an_active_members_session_is_extended_each_time_the_visit_is_recorded(self, auth_client, user, settings):
        type(user).objects.filter(pk=user.pk).update(last_activity_at=timezone.now() - inactivity.ACTIVITY_REFRESH - timedelta(minutes=1))
        auth_client.get(reverse("index"))
        expiry = Session.objects.get().expire_date
        assert expiry - timezone.now() > timedelta(seconds=settings.SESSION_COOKIE_AGE - 120)

    def test_the_session_lasts_six_months_not_a_year(self, settings):
        assert settings.SESSION_COOKIE_AGE == 60 * 60 * 24 * 183


class TestScheduledTask:
    URL = "/cron/purge-inactive-accounts/"

    def test_an_authorized_call_also_clears_expired_sessions(self, client, settings):
        settings.CRON_SECRET = "s3cret"
        Session.objects.create(session_key="old", session_data="x", expire_date=timezone.now() - timedelta(days=1))
        assert client.get(self.URL, HTTP_AUTHORIZATION="Bearer s3cret").status_code == 200
        assert not Session.objects.filter(session_key="old").exists()

    def test_a_non_ascii_header_is_refused_not_crashing(self, client, settings):
        settings.CRON_SECRET = "s3cret"
        assert client.get(self.URL, HTTP_AUTHORIZATION="Bearer é€").status_code == 403

    def test_without_the_secret_nothing_is_cleared(self, client, settings):
        settings.CRON_SECRET = "s3cret"
        Session.objects.create(session_key="old", session_data="x", expire_date=timezone.now() - timedelta(days=1))
        assert client.get(self.URL).status_code == 403
        assert Session.objects.filter(session_key="old").exists()


class TestRandomSampleWithoutSorting:
    def test_returns_the_requested_number_from_the_catalogue(self):
        from app.models import Beer
        beers = [f.make_beer() for _ in range(15)]
        sample = ai._random_sample(Beer.objects.all(), 10)
        assert len(sample) == 10 and len({b.pk for b in sample}) == 10 and set(sample) <= set(beers)

    def test_a_small_catalogue_is_returned_whole(self):
        from app.models import Beer
        beers = [f.make_beer() for _ in range(3)]
        assert set(ai._random_sample(Beer.objects.all(), 10)) == set(beers)

    def test_an_empty_catalogue_gives_nothing(self):
        from app.models import Beer
        assert ai._random_sample(Beer.objects.all(), 10) == []

    def test_no_random_ordering_is_ever_used(self):
        from app.models import Beer
        f.make_beer()
        with CaptureQueriesContext(connection) as queries:
            ai._random_sample(Beer.objects.all(), 5)
        assert not any("RANDOM()" in q["sql"].upper() for q in queries)

    def test_the_chat_context_never_proposes_a_blocked_members_beer(self, user, other_user, beer, monkeypatch):
        monkeypatch.setattr(ai, "get_embedding", lambda text: None)
        assert beer in ai._select_beers("une blonde", user=user)
        f.block(other_user, user)
        assert beer not in ai._select_beers("une blonde", user=user)


class TestCachedLists:
    def test_the_style_filter_follows_the_catalogue(self):
        from app.views.search_views import beer_styles
        assert beer_styles() == []
        f.make_beer(style="IPA, Stout")
        assert beer_styles() == ["IPA", "Stout"]
        beer = f.make_beer(style="Sour")
        assert "Sour" in beer_styles()
        beer.is_deleted = True
        beer.save()
        assert "Sour" not in beer_styles()

    def test_the_map_markers_follow_the_places(self, geocoder):
        from app.services.establishments import place_directory
        assert place_directory.map_markers() == {"bar": [], "brewery": []}
        bar = f.make_bar(address="Lyon")
        assert [m["slug"] for m in place_directory.map_markers()["bar"]] == [bar.slug]
        bar.delete()
        assert place_directory.map_markers()["bar"] == []


class TestNotificationTexts:
    def test_every_declared_type_has_its_text_template(self):
        from django.template.loader import get_template
        from app.services.messaging import notification_types
        for notification_type in notification_types.REGISTRY.values():
            get_template(notification_type.text_template)  # lève TemplateDoesNotExist s'il manque

    def test_every_template_belongs_to_a_declared_type(self):
        from pathlib import Path
        from django.conf import settings
        from app.services.messaging import notification_types
        files = {p.stem for p in Path(settings.BASE_DIR, "app", "templates", "partials", "notifications").glob("*.html")}
        assert files == set(notification_types.REGISTRY)
