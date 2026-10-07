"""Administration des campagnes e-mail : réservée aux superusers, actions en POST, contenu validé."""
import pytest
from django.core import mail
from django.urls import reverse

from app.models import EmailCampaign
from tests import factories as f

pytestmark = pytest.mark.django_db

ADD, LIST = reverse("admin:app_emailcampaign_add"), reverse("admin:app_emailcampaign_changelist")


def change(campaign):
    return reverse("admin:app_emailcampaign_change", args=[campaign.pk])


def act(campaign, name):
    return reverse("admin:app_emailcampaign_action", args=[campaign.pk, name])


def data(**overrides):
    return {
        "subject": "Du nouveau", "body": "Bonjour {username} !", "cta_label": "", "cta_url": "",
        "kind": "promotional", "audience": "all", "activity_days": 90, "custom_members": [], **overrides,
    }


@pytest.fixture
def superuser(db):
    """Superuser désinscrit des e-mails promotionnels : il ne compte pas parmi les destinataires."""
    return f.make_user(username="root", is_superuser=True, groups=("Staff",), marketing_opt_in=False)


@pytest.fixture
def draft(db):
    return EmailCampaign.objects.create(subject="Brouillon", body="Salut {username}", audience="all")


def fan(opt_in=True):
    return f.make_user(marketing_opt_in=opt_in)


class TestAccess:
    @pytest.mark.parametrize("url", [LIST, ADD])
    def test_staff_without_superuser_is_refused(self, client_for, staff, url):
        assert client_for(staff).get(url).status_code in (302, 403)

    def test_anonymous_is_refused(self, client, draft):
        for url in (LIST, change(draft), reverse("admin:app_emailcampaign_preview", args=[draft.pk])):
            assert client.get(url).status_code == 302

    @pytest.mark.parametrize("name", ["test", "launch", "batch", "cancel"])
    def test_actions_are_refused_to_staff(self, client_for, staff, draft, name):
        assert client_for(staff).post(act(draft, name)).status_code in (302, 403, 404)
        assert EmailCampaign.objects.get().status == "draft" and mail.outbox == []

    def test_actions_only_accept_post(self, client_for, superuser, draft):
        assert client_for(superuser).get(act(draft, "launch")).status_code == 405

    def test_unknown_action_is_a_404(self, client_for, superuser, draft):
        assert client_for(superuser).post(act(draft, "explode")).status_code == 404

    def test_admin_pages_still_resolve(self, client_for, superuser, draft):
        client = client_for(superuser)
        assert client.get(LIST).status_code == 200 and client.get(change(draft)).status_code == 200
        assert client.get(reverse("admin:app_emailcampaign_delete", args=[draft.pk])).status_code == 200


class TestWriting:
    def test_creating_records_the_author(self, client_for, superuser):
        response = client_for(superuser).post(ADD, data())
        assert response.status_code == 302 and EmailCampaign.objects.get().created_by == superuser

    @pytest.mark.parametrize("overrides", [
        {"cta_label": "Voir"},                                        # texte sans lien
        {"cta_url": "https://pokebeer.test/map/"},                    # lien sans texte
        {"cta_label": "Voir", "cta_url": "https://evil.example/login"},   # domaine tiers
        {"cta_label": "Voir", "cta_url": "https://pokebeer.test.evil.example/"},
        {"cta_label": "Voir", "cta_url": "javascript:alert(1)"},
        {"cta_label": "Installer", "cta_url": "https://play.google.com/store/apps/details?id=com.scarone.pokebeer"},
        {"subject": "Objet\nBcc: x@evil.example"},
        {"activity_days": 1},
        {"audience": "custom", "custom_members": []},
    ])
    def test_invalid_campaigns_are_refused(self, client_for, superuser, overrides):
        assert client_for(superuser).post(ADD, data(**overrides)).status_code == 200
        assert not EmailCampaign.objects.exists()

    def test_links_to_the_site_are_accepted(self, client_for, superuser):
        assert client_for(superuser).post(ADD, data(cta_label="Voir", cta_url="https://pokebeer.test/map/")).status_code == 302

    def test_the_custom_list_is_chosen_from_members_shown_as_pseudo_dash_email(self, client_for, superuser):
        alpha, bravo, suspended = fan(), fan(), f.make_user(is_active=False)
        client = client_for(superuser)
        page = client.get(ADD).content.decode()
        assert f"{alpha.username} - {alpha.email}" in page and suspended.email not in page
        assert client.post(ADD, data(audience="custom", custom_members=[alpha.pk, bravo.pk])).status_code == 302
        assert set(EmailCampaign.objects.get().custom_members.all()) == {alpha, bravo}

    def test_a_custom_list_is_capped(self, client_for, superuser, monkeypatch):
        from app.services import campaigns
        monkeypatch.setattr(campaigns, "MAX_CUSTOM_MEMBERS", 1)
        chosen = [fan().pk, fan().pk]
        assert client_for(superuser).post(ADD, data(audience="custom", custom_members=chosen)).status_code == 200
        assert not EmailCampaign.objects.exists()

    def test_a_launched_campaign_is_frozen(self, client_for, superuser, draft):
        fan()
        client = client_for(superuser)
        client.post(act(draft, "launch"))
        page = client.get(change(draft))  # la page d'une campagne lancée s'affiche en lecture seule
        assert page.status_code == 200 and "Brouillon" in page.content.decode()
        assert client.post(change(draft), data(subject="Modifié")).status_code in (302, 403) and EmailCampaign.objects.get().subject == "Brouillon"
        assert client.post(reverse("admin:app_emailcampaign_delete", args=[draft.pk]), {"post": "yes"}).status_code == 403


class TestActions:
    def test_the_page_shows_the_audience_and_what_consent_leaves_out(self, client_for, superuser, draft):
        fan(), fan(False)
        page = client_for(superuser).get(change(draft)).content.decode()
        assert "<strong>1</strong> destinataire(s)" in page and "désinscrit(s) des e-mails promotionnels" in page
        assert reverse("admin:app_emailcampaign_preview", args=[draft.pk]) in page and "csrfmiddlewaretoken" in page

    def test_preview_renders_the_email_for_the_admin(self, client_for, superuser, draft):
        html = client_for(superuser).get(reverse("admin:app_emailcampaign_preview", args=[draft.pk])).content.decode()
        assert "Salut root" in html and "emails/preferences/" in html

    def test_test_email_goes_to_the_admin(self, client_for, superuser, draft):
        fan()
        client_for(superuser).post(act(draft, "test"))
        assert [m.to[0] for m in mail.outbox] == [superuser.email] and mail.outbox[0].subject.startswith("[TEST]")

    def test_launch_sends_the_first_batch_and_goes_to_the_campaign_page(self, client_for, superuser, draft):
        target = fan()
        response = client_for(superuser).post(act(draft, "launch"))
        assert response.url == change(draft) and [m.to[0] for m in mail.outbox] == [target.email]
        launched = EmailCampaign.objects.get()
        assert launched.status == "done" and launched.launched_by == superuser

    def test_launch_without_recipients_explains_why(self, client_for, superuser, draft):
        fan(False)
        client = client_for(superuser)
        page = client.post(act(draft, "launch"), follow=True).content.decode()
        assert "Aucun destinataire" in page and EmailCampaign.objects.get().status == "draft"

    def test_a_mandatory_alert_needs_the_explicit_attestation(self, client_for, superuser):
        alert = EmailCampaign.objects.create(subject="Sécurité", body="Important", kind="service", audience="all")
        refuser = fan(False)
        client = client_for(superuser)
        client.post(act(alert, "launch"))
        assert EmailCampaign.objects.get().status == "draft" and mail.outbox == []
        client.post(act(alert, "launch"), {"confirm_service": "on"})
        assert EmailCampaign.objects.get().status == "done"
        assert {m.to[0] for m in mail.outbox} == {refuser.email, superuser.email}  # même celui qui a refusé les e-mails promotionnels

    def test_next_batch_and_cancel(self, client_for, superuser, draft, monkeypatch):
        from app.services import campaigns
        monkeypatch.setattr(campaigns, "ADMIN_BATCH", 1)
        for _ in range(3):
            fan()
        client = client_for(superuser)
        client.post(act(draft, "launch"))
        assert len(mail.outbox) == 1
        client.post(act(draft, "batch"))
        assert len(mail.outbox) == 2
        client.post(act(draft, "cancel"))
        client.post(act(draft, "batch"))
        assert len(mail.outbox) == 2 and EmailCampaign.objects.get().status == "cancelled"

    def test_launching_twice_does_not_resend(self, client_for, superuser, draft):
        fan()
        client = client_for(superuser)
        client.post(act(draft, "launch"))
        client.post(act(draft, "launch"))
        assert len(mail.outbox) == 1
