import pytest
from django.contrib import admin
from django.urls import reverse

from app.services.blocks import REPEATED_BLOCK_THRESHOLD, repeatedly_blocked_count
from app.models import UserBlock
from tests import factories as f

pytestmark = pytest.mark.django_db
URL = "admin:app_userblock_changelist"


def block_many(target, count):
    for _ in range(count):
        f.block(f.make_user(username=f.unique("blocker_")), target)


class TestBlockedMembersView:
    def test_superuser_sees_who_blocked_whom(self, client_for, superuser, user, other_user):
        f.block(user, other_user)
        response = client_for(superuser).get(reverse(URL))
        html = response.content.decode()
        assert response.status_code == 200 and "alice" in html and "bobby" in html

    def test_staff_and_members_are_refused(self, client_for, staff, auth_client, user, other_user):
        f.block(user, other_user)
        assert client_for(staff).get(reverse(URL)).status_code == 403
        assert auth_client.get(reverse(URL)).status_code == 302

    def test_view_is_read_only(self, client_for, superuser, user, other_user):
        block = f.block(user, other_user)
        client = client_for(superuser)
        assert client.get(reverse("admin:app_userblock_add")).status_code == 403
        assert client.post(reverse("admin:app_userblock_delete", args=[block.pk]), {"post": "yes"}).status_code == 403
        assert UserBlock.objects.filter(pk=block.pk).exists()

    def test_repeated_blocks_are_counted_per_distinct_blocker(self, client_for, superuser, other_user):
        block_many(other_user, REPEATED_BLOCK_THRESHOLD)
        f.block(f.make_user(username=f.unique("loner_")), f.make_user(username=f.unique("calm_")))
        assert repeatedly_blocked_count() == 1
        response = client_for(superuser).get(reverse(URL), {"blocked_by": str(REPEATED_BLOCK_THRESHOLD)})
        assert response.context["cl"].result_count == REPEATED_BLOCK_THRESHOLD
        assert response.context["pending_count"] == 1

    def test_reports_received_are_shown(self, client_for, superuser, user, other_user):
        f.block(user, other_user)
        f.make_report(user, reported_user=other_user)
        rows = client_for(superuser).get(reverse(URL)).context["cl"].result_list
        assert rows[0].reports_received == 1

    def test_sidebar_entry_is_superuser_only(self, settings):
        item = next(i for g in settings.UNFOLD["SIDEBAR"]["navigation"] for i in g["items"] if i["title"] == "Personnes bloquées")
        assert item["permission"](type("R", (), {"user": type("U", (), {"is_superuser": False})()})()) is False
