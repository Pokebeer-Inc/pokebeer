"""Tableau de bord : bouton d'annonce de la politique de confidentialité, réservé aux superusers."""
import pytest
from django.urls import reverse

from app.models import Notification, PolicyNotice
from tests import factories as f

pytestmark = pytest.mark.django_db

PUBLISH = "admin:app_policynotice_publish"


def publish(client, **data):
    return client.post(reverse(PUBLISH), {"summary": "ajout des e-mails de service", **data})


def test_dashboard_shows_the_form_and_the_history(client_for, superuser, user):
    page = client_for(superuser).get(reverse("admin:index")).content.decode()
    assert "Notifier tous les membres" in page and reverse(PUBLISH) in page
    publish(client_for(superuser))
    assert "ajout des e-mails de service" in client_for(superuser).get(reverse("admin:index")).content.decode()


def test_superuser_notifies_everyone(client_for, superuser, user, other_user):
    response = publish(client_for(superuser))
    assert response.status_code == 302
    notice = PolicyNotice.objects.get()
    assert notice.created_by == superuser and notice.notified_count == 3 and not notice.notify_by_email
    assert Notification.objects.filter(notif_type="policy_updated").count() == 3


def test_email_option_is_recorded(client_for, superuser, user):
    publish(client_for(superuser), notify_by_email="on")
    notice = PolicyNotice.objects.get()
    assert notice.notify_by_email and not notice.email_done


@pytest.mark.parametrize("summary", ["", "x" * 201, "<script>alert(1)</script>"])
def test_invalid_summaries_send_nothing(client_for, superuser, user, summary):
    publish(client_for(superuser), summary=summary)
    assert not PolicyNotice.objects.exists() and not Notification.objects.exists()


def test_staff_who_is_not_superuser_cannot_publish(client_for, staff, user):
    response = publish(client_for(staff))
    assert response.status_code in (302, 403) and not PolicyNotice.objects.exists()


def test_members_cannot_publish(auth_client):
    assert publish(auth_client).status_code == 302
    assert not PolicyNotice.objects.exists()


def test_publishing_requires_a_post(client_for, superuser):
    assert client_for(superuser).get(reverse(PUBLISH)).status_code == 405


def test_a_second_announcement_is_refused_right_after(client_for, superuser, user):
    for _ in range(3):
        publish(client_for(superuser))
    assert PolicyNotice.objects.count() == 2


def test_history_page_is_read_only_and_superuser_only(client_for, superuser, staff):
    f.make_user()
    assert client_for(superuser).get(reverse("admin:app_policynotice_changelist")).status_code == 200
    assert client_for(superuser).get(reverse("admin:app_policynotice_add")).status_code == 403
    assert client_for(staff).get(reverse("admin:app_policynotice_changelist")).status_code == 403
