"""Annonce de la politique de confidentialité : formulaire en tête de la liste des annonces, réservé aux superusers."""
import pytest
from django.urls import reverse

from app.models import Notification, PolicyNotice
from tests import factories as f

pytestmark = pytest.mark.django_db

PUBLISH = "admin:app_policynotice_publish"


def publish(client, **data):
    return client.post(reverse(PUBLISH), {"summary": "ajout des e-mails de service", **data})


LIST = "admin:app_policynotice_changelist"


def test_the_form_sits_above_the_list_of_announcements(client_for, superuser, user):
    publish(client_for(superuser), summary="RESUME-UNIQUE-XYZ")
    page = client_for(superuser).get(reverse(LIST)).content.decode()
    assert "Notifier tous les membres" in page and reverse(PUBLISH) in page and "csrfmiddlewaretoken" in page
    assert page.index("Notifier tous les membres") < page.index("RESUME-UNIQUE-XYZ")  # le formulaire précède la liste


def test_the_form_links_to_the_configured_policy(client_for, superuser, settings):
    settings.PRIVACY_POLICY_URL = "https://policy.example/doc"
    assert 'href="https://policy.example/doc"' in client_for(superuser).get(reverse(LIST)).content.decode()


def test_the_dashboard_no_longer_carries_the_form(client_for, superuser):
    assert "Notifier tous les membres" not in client_for(superuser).get(reverse("admin:index")).content.decode()


def test_publishing_returns_to_the_list(client_for, superuser, user):
    assert publish(client_for(superuser)).url == reverse(LIST)


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
