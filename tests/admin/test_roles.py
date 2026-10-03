"""Page « Rôles » : attribution, retrait, droits, journalisation."""
import pytest
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.test import RequestFactory
from django.urls import reverse

from app.admin import dashboard_callback
from app.models import BeerUser
from tests import factories as f

pytestmark = pytest.mark.django_db


def admin_request(user):
    request = RequestFactory().post("/admin/")
    request.user = user
    return request


class TestRolesPage:
    url = staticmethod(lambda: reverse("admin:app_beeruser_roles"))

    def post(self, client, user, role, op):
        return client.post(self.url(), {"user": user.pk, "role": role, "op": op})

    def test_new_member_is_contributor_and_roles_accumulate(self, client_for, superuser):
        member = f.make_user()
        client = client_for(superuser)
        self.post(client, member, "brewer", "add")
        self.post(client, member, "staff", "add")
        names = set(member.groups.values_list("name", flat=True))
        assert names == {"Contributeur", "Brasseur", "Staff"}

    def test_page_lists_members_and_filters_by_role(self, client_for, superuser):
        f.make_user(username="brasseur1", groups=("Brasseur",))
        f.make_user(username="simple1")
        response = client_for(superuser).get(self.url(), {"role": "brewer"})
        assert response.status_code == 200
        assert b"brasseur1" in response.content and b"simple1" not in response.content

    def test_contributor_cannot_be_removed(self, client_for, superuser):
        member = f.make_user()
        self.post(client_for(superuser), member, "contributor", "remove")
        assert member.groups.filter(name="Contributeur").exists()

    def test_granting_admin_also_gives_staff_access(self, client_for, superuser):
        member = f.make_user()
        self.post(client_for(superuser), member, "admin", "add")
        member = BeerUser.objects.get(pk=member.pk)
        assert member.is_superuser and member.is_staff

    def test_revoking_brewer(self, client_for, superuser):
        member = f.make_user(groups=("Brasseur",))
        self.post(client_for(superuser), member, "brewer", "remove")
        assert not member.groups.filter(name="Brasseur").exists()

    def test_cannot_remove_own_admin_rights(self, client_for, superuser):
        self.post(client_for(superuser), superuser, "admin", "remove")
        assert BeerUser.objects.get(pk=superuser.pk).is_superuser

    def test_staff_can_view_but_not_change_roles(self, client_for, staff):
        member = f.make_user()
        client = client_for(staff)
        self.post(client, member, "brewer", "add")
        assert not member.groups.filter(name="Brasseur").exists()

    def test_user_changelist_shows_role_badges(self, client_for, superuser):
        f.make_user(username="duo1", groups=("Brasseur", "Bartender"))
        response = client_for(superuser).get(reverse("admin:app_beeruser_changelist"))
        assert response.status_code == 200
        assert b"Brasseur" in response.content and b"Bartender" in response.content


class TestRolesSecurityAndAudit:
    def test_role_fields_are_readonly_on_user_form(self, superuser):
        model_admin = admin.site._registry[BeerUser]
        readonly = model_admin.get_readonly_fields(admin_request(superuser), superuser)
        assert {"groups", "is_superuser"} <= set(readonly)

    def test_permissions_field_locked_for_non_superuser(self, staff):
        model_admin = admin.site._registry[BeerUser]
        assert "user_permissions" in model_admin.get_readonly_fields(admin_request(staff), staff)

    def test_role_change_is_logged_in_django_log_entries(self, client_for, superuser):
        member = f.make_user()
        client_for(superuser).post(reverse("admin:app_beeruser_roles"), {"user": member.pk, "role": "bartender", "op": "add"})
        entry = LogEntry.objects.get(object_id=str(member.pk))
        assert entry.user == superuser and "Bartender" in entry.change_message

    def test_refused_change_is_not_logged(self, client_for, staff):
        member = f.make_user()
        client_for(staff).post(reverse("admin:app_beeruser_roles"), {"user": member.pk, "role": "bartender", "op": "add"})
        assert not LogEntry.objects.exists()

    def test_open_redirect_is_ignored(self, client_for, superuser):
        member = f.make_user()
        response = client_for(superuser).post(reverse("admin:app_beeruser_roles"), {"user": member.pk, "role": "brewer", "op": "add", "next": "https://evil.example/"})
        assert response.url == reverse("admin:app_beeruser_roles")

    def test_get_with_unknown_method_is_rejected(self, client_for, superuser):
        assert client_for(superuser).delete(reverse("admin:app_beeruser_roles")).status_code == 405

    def test_dashboard_context_counts_roles(self, superuser):
        f.make_user(groups=("Brasseur",))
        context = {}
        dashboard_callback(admin_request(superuser), context)
        assert context["kpi_roles"]["brewer"] == 1 and context["kpi_roles"]["admin"] == 1

    def test_user_change_form_and_history_render(self, client_for, superuser):
        member = f.make_user()
        client = client_for(superuser)
        assert client.get(reverse("admin:app_beeruser_change", args=[member.pk])).status_code == 200
        client.post(reverse("admin:app_beeruser_roles"), {"user": member.pk, "role": "brewer", "op": "add"})
        assert b"Brasseur" in client.get(reverse("admin:app_beeruser_history", args=[member.pk])).content
