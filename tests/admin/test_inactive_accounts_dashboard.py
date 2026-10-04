"""Tableau de bord RGPD des comptes inactifs."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from app.models import AccountDeletion
from app.services import inactivity
from tests import factories as f
from tests.unit.test_inactive_accounts import IN_WARNING_WINDOW, LONG_AGO, idle

pytestmark = pytest.mark.django_db


class TestDashboard:
    def test_shows_counters_and_alerts(self, client_for, superuser, user):
        idle(user, LONG_AGO)
        idle(f.make_user(), IN_WARNING_WINDOW)
        idle(f.make_user(), LONG_AGO, warned_days_ago=31)
        stats = inactivity.dashboard_stats()
        assert (stats["to_warn"], stats["unwarned_overdue"], stats["awaiting_deletion"]) == (2, 1, 1)
        page = client_for(superuser).get(reverse("admin:index")).content.decode()
        assert "Comptes inactifs (RGPD)" in page and "ne semble pas s'exécuter" in page

    def test_lists_deletions_and_upcoming(self, client_for, superuser, user):
        idle(user, LONG_AGO, warned_days_ago=10)
        AccountDeletion.objects.create(user_id=999, reason="self", last_activity_at=timezone.now())
        stats = inactivity.dashboard_stats()
        assert [item["user"] for item in stats["upcoming"]] == [user]
        assert stats["deleted_total"] == 1 and stats["deleted_30d"] == 1
        page = client_for(superuser).get(reverse("admin:index")).content.decode()
        assert "Compte n°999" in page and user.username in page

    def test_member_filter_and_log_are_reachable(self, client_for, superuser, user):
        idle(user, LONG_AGO, warned_days_ago=31)
        client = client_for(superuser)
        response = client.get(reverse("admin:app_beeruser_changelist"), {"inactivity": "due"})
        assert response.status_code == 200 and user.username in response.content.decode()
        assert client.get(reverse("admin:app_accountdeletion_changelist")).status_code == 200
