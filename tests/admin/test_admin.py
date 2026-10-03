from types import SimpleNamespace
from unittest import mock

import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse

from app.admin import dashboard_callback
from app.admin.pending import pending_feedback_count, pending_report_count
from app.models import Bar, BeerUser, Feedback, Notification, Report
from tests import factories as f
from tests.helpers import messages_of

pytestmark = pytest.mark.django_db


def admin_request(user):
    request = RequestFactory().post("/admin/")
    request.user = user
    return request


def save_through_admin(model, obj, user, changed, change=True):
    model_admin = admin.site._registry[model]
    model_admin.save_model(admin_request(user), obj, SimpleNamespace(changed_data=changed), change)


class TestAdminAccess:
    def test_staff_superuser_reaches_the_dashboard(self, client_for, superuser):
        assert client_for(superuser).get(reverse("admin:index")).status_code == 200

    def test_regular_member_is_sent_to_admin_login(self, auth_client):
        response = auth_client.get(reverse("admin:index"))
        assert response.status_code == 302 and "/admin/login/" in response.url


class TestVerifyBar:
    def url(self, bar):
        return reverse("admin:bar_verify", args=[bar.slug])

    def test_get_is_not_allowed(self, client_for, superuser):
        bar = f.make_bar()
        assert client_for(superuser).get(self.url(bar)).status_code == 405

    def test_staff_without_superuser_rights_is_forbidden(self, client_for, staff):
        bar = f.make_bar()
        assert client_for(staff).post(self.url(bar)).status_code == 403
        assert not Bar.objects.get(pk=bar.pk).is_verified

    def test_superuser_verifies_the_bar(self, client_for, superuser):
        bar = f.make_bar()
        assert client_for(superuser).post(self.url(bar)).json() == {"success": True, "bar_slug": bar.slug, "is_verified": True}
        bar.refresh_from_db()
        assert (bar.is_verified, bar.verified_by, bar.verified_at is not None) == (True, superuser, True)

    def test_unknown_bar_is_404(self, client_for, superuser):
        assert client_for(superuser).post(reverse("admin:bar_verify", args=["unknown-slug"])).status_code == 404


class TestReportAdmin:
    @pytest.mark.parametrize("changed, notified", [(["status"], True), (["admin_response"], True), ([], False)])
    def test_reporter_is_notified_only_when_the_decision_changes(self, superuser, user, changed, notified):
        report = f.make_report(user)
        report.status = "resolved"
        save_through_admin(Report, report, superuser, changed)
        assert Notification.objects.filter(recipient=user, notif_type="report_updated", report=report).exists() is notified

    def test_creation_from_admin_does_not_notify(self, superuser, user):
        save_through_admin(Report, Report(reporter=user, reason="spam", description="x"), superuser, ["status"], change=False)
        assert not Notification.objects.exists()

    def test_target_label(self, user, other_user, beer):
        report_admin = admin.site._registry[Report]
        reports = [f.make_report(user, **target) for target in (
            {"reported_beer": beer}, {"reported_drink": f.make_drink(other_user, beer)}, {"reported_user": other_user},
            {"reported_brewery": beer.brewery_id}, {},
        )]
        assert [report_admin.target_type(r) for r in reports] == ["Bière", "Note", "Utilisateur", "Brasserie", "Inconnu"]
        assert report_admin.get_target(reports[3]) == beer.brewery_id.name

    def test_brewery_filter_lists_only_brewery_reports(self, client_for, superuser, user, beer):
        brewery_report = f.make_report(user, reported_brewery=beer.brewery_id)
        f.make_report(user, reported_beer=beer)
        response = client_for(superuser).get(reverse("admin:app_report_changelist"), {"target_type": "brewery"})
        assert list(response.context["cl"].result_list) == [brewery_report]


class TestFeedbackAdmin:
    def test_reply_marks_as_replied_and_notifies(self, superuser, user):
        feedback = f.make_feedback(user)
        feedback.admin_reply = "Merci !"
        save_through_admin(Feedback, feedback, superuser, ["admin_reply"])
        assert Feedback.objects.get(pk=feedback.pk).status == "replied"
        assert Notification.objects.get().notif_type == "feedback_replied"

    @pytest.mark.parametrize("reply, changed", [("", ["admin_reply"]), ("Merci", [])])
    def test_no_notification_without_a_new_reply(self, superuser, user, reply, changed):
        feedback = f.make_feedback(user, admin_reply=reply)
        save_through_admin(Feedback, feedback, superuser, changed)
        assert not Notification.objects.exists()


class TestAccountSuspension:
    URL = reverse("admin:app_beeruser_changelist")

    def run_action(self, client, action, *users):
        return client.post(self.URL, {"action": action, "_selected_action": [u.pk for u in users]}, follow=True)

    def is_active(self, user):
        return BeerUser.objects.get(pk=user.pk).is_active

    def test_superuser_suspends_then_reactivates_a_member(self, client_for, superuser, user):
        client = client_for(superuser)
        self.run_action(client, "suspend_accounts", user)
        assert not self.is_active(user)
        self.run_action(client, "reactivate_accounts", user)
        assert self.is_active(user)

    def test_suspended_filter_lists_only_suspended_accounts(self, client_for, superuser, user, other_user):
        BeerUser.objects.filter(pk=user.pk).update(is_active=False)
        response = client_for(superuser).get(self.URL, {"is_active__exact": "0"})
        assert [u.username for u in response.context["cl"].result_list] == ["alice"]

    def test_nobody_can_suspend_their_own_account(self, client_for, superuser, user):
        response = self.run_action(client_for(superuser), "suspend_accounts", superuser, user)
        assert self.is_active(superuser) and not self.is_active(user)
        assert any("ignoré" in message for message in messages_of(response))

    def test_staff_cannot_suspend_a_superuser(self, superuser, staff):
        model_admin = admin.site._registry[BeerUser]
        request = admin_request(staff)
        request._messages = mock.Mock()
        model_admin.set_active(request, BeerUser.objects.filter(pk=superuser.pk), False)
        assert self.is_active(superuser)

    def test_superuser_can_suspend_another_superuser(self, superuser):
        other_root = f.make_user(username="root2", is_superuser=True)
        model_admin = admin.site._registry[BeerUser]
        request = admin_request(superuser)
        request._messages = mock.Mock()
        model_admin.set_active(request, BeerUser.objects.filter(pk=other_root.pk), False)
        assert not self.is_active(other_root)

    @pytest.mark.parametrize("editor, target, readonly", [
        ("staff", "superuser", True), ("staff", "staff", True), ("superuser", "superuser", True),
        ("staff", "user", False), ("superuser", "staff", False),
    ])
    def test_active_flag_is_read_only_on_protected_accounts(self, request, editor, target, readonly):
        editor, target = request.getfixturevalue(editor), request.getfixturevalue(target)
        fields = admin.site._registry[BeerUser].get_readonly_fields(admin_request(editor), target)
        assert ("is_active" in fields) is readonly


class TestDashboard:
    def test_kpis_and_geolocated_bars(self, superuser, beer, geocoder):
        located = f.make_bar(address="Paris")
        f.make_bar(address=None)
        f.make_report(superuser)

        context = dashboard_callback(admin_request(superuser), {})

        assert (context["kpi_beers"], context["kpi_brewery"], context["kpi_report"]) == (1, 1, 1)
        assert [bar["slug"] for bar in context["bars"]] == [located.slug]
        assert context["bars"][0]["verify_url"] == reverse("admin:bar_verify", args=[located.slug])
        assert context["beer_count_by_style"] == [{"style": "IPA", "nb_bieres": 1}]

    def test_deleted_beers_are_not_in_the_style_chart(self, superuser, beer):
        f.make_beer(style="Stout", is_deleted=True)
        context = dashboard_callback(admin_request(superuser), {})
        assert [row["style"] for row in context["beer_count_by_style"]] == ["IPA"]

    @pytest.mark.parametrize("kpi, url_name", [
        ("Utilisateurs", "admin:app_beeruser_changelist"), ("Bières", "admin:app_beer_changelist"),
        ("Brasseries", "admin:app_brewery_changelist"), ("Signalements", "admin:app_report_changelist"),
    ])
    def test_first_row_kpis_link_to_their_list(self, client_for, superuser, kpi, url_name):
        html = client_for(superuser).get(reverse("admin:index")).content.decode()
        card = html[html.index(f'<a href="{reverse(url_name)}" class="block'):]
        assert kpi in card[:400]


class TestPendingCounters:
    def test_feedback_counts_only_unanswered(self, user):
        Feedback.objects.create(user=user, message="a")
        Feedback.objects.create(user=user, message="b", status="replied")
        assert pending_feedback_count() == 1

    def test_reports_exclude_resolved_ones(self, user):
        f.make_report(user, status="pending")
        f.make_report(user, status="review")
        f.make_report(user, status="resolved")
        assert pending_report_count() == 2

    @pytest.mark.parametrize("url_name, expected", [("admin:app_feedback_changelist", "1"), ("admin:app_report_changelist", "1")])
    def test_changelist_shows_the_pending_kpi(self, client_for, superuser, user, url_name, expected):
        Feedback.objects.create(user=user, message="a")
        Feedback.objects.create(user=user, message="b", status="replied")
        f.make_report(user)
        f.make_report(user, status="resolved")
        response = client_for(superuser).get(reverse(url_name))
        assert response.context["pending_count"] == int(expected)

    def test_sidebar_badges_are_configured(self, settings):
        badges = {item["title"]: item.get("badge") for group in settings.UNFOLD["SIDEBAR"]["navigation"] for item in group["items"]}
        assert badges["Feedback"] == "app.admin.pending.pending_feedback_count"
        assert badges["Signalement"] == "app.admin.pending.pending_report_count"


class TestMapFixes:
    def test_osm_tiles_receive_a_referer(self, settings):
        # same-origin (défaut Django) prive OpenStreetMap du Referer : tuiles refusées en 403 en production
        assert settings.SECURE_REFERRER_POLICY == "strict-origin-when-cross-origin"

    def test_leaflet_css_integrity_matches_the_other_pages(self):
        from pathlib import Path
        templates = Path("app/templates")
        hashes = {
            line.split('integrity="')[1].split('"')[0]
            for path in templates.rglob("*.html") for line in path.read_text().splitlines()
            if "leaflet.css" in line and 'integrity="' in line
        } | {"sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="}
        admin_template = (templates / "admin/bar_moderation.html").read_text()
        assert "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" in admin_template
        assert len(hashes) == 1
