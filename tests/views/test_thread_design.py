import pytest
from django.urls import reverse

from app.services import feedback as conversations
from app.services.threads import RESOLVED_DEFAULT_MESSAGE, report_entries
from tests import factories as f

pytestmark = pytest.mark.django_db
SHARED_CSS = "style/thread_ui.css"


class TestReportEntries:
    def test_report_then_team_decision(self, user):
        report = f.make_report(user, description="Spam évident", admin_response="Compte averti")
        entries = report_entries(report)
        assert [(e.is_team, e.body) for e in entries] == [(False, "Spam évident"), (True, "Compte averti")]
        assert entries[0].created_at == report.created_at and entries[1].created_at is None

    def test_resolved_without_a_decision_gets_the_default_message(self, user):
        entries = report_entries(f.make_report(user, status="resolved"))
        assert entries[-1].is_team and entries[-1].body == RESOLVED_DEFAULT_MESSAGE

    def test_pending_report_has_no_team_message_yet(self, user):
        assert len(report_entries(f.make_report(user))) == 1


class TestSameDesignEverywhere:
    def test_reports_use_the_conversation_bubbles_read_only(self, auth_client, user):
        f.make_report(user, description="Contenu choquant", admin_response="Contenu retiré")
        html = auth_client.get(reverse("my_reports")).content.decode()
        assert SHARED_CSS in html and "team-chat-bubble" in html and "thread-card" in html
        assert html.index("Contenu choquant") < html.index("Contenu retiré")
        assert "Équipe Pokebeer" in html and "votre signalement" in html

    def test_reports_page_offers_no_way_to_send_messages(self, auth_client, user):
        f.make_report(user)
        html = auth_client.get(reverse("my_reports")).content.decode()
        assert 'id="reply"' not in html and 'name="body"' not in html

    def test_report_status_badges(self, auth_client, user):
        for status in ("pending", "review", "resolved"):
            f.make_report(user, status=status)
        html = auth_client.get(reverse("my_reports")).content.decode()
        assert all(css in html for css in ("thread-status--waiting", "thread-status--review", "thread-status--done"))

    def test_report_text_is_escaped(self, auth_client, user):
        f.make_report(user, description="<script>alert(1)</script>", admin_response="<img src=x onerror=alert(1)>")
        html = auth_client.get(reverse("my_reports")).content.decode()
        assert "<script>alert(1)" not in html and "<img src=x" not in html

    def test_blocked_accounts_use_the_same_cards(self, auth_client, user, other_user):
        f.block(user, other_user)
        html = auth_client.get(reverse("blocked_users")).content.decode()
        assert SHARED_CSS in html and "thread-card" in html and "thread-status" in html
        assert "Bloqué le" in html and other_user.avatar_url in html

    def test_empty_states_share_the_same_style(self, auth_client):
        for name in ("my_reports", "blocked_users", "team_messages"):
            assert "thread-empty" in auth_client.get(reverse(name)).content.decode()

    def test_messages_list_and_thread_use_the_shared_stylesheet(self, auth_client, user):
        thread = conversations.open_thread(user, "Bonjour")
        assert SHARED_CSS in auth_client.get(reverse("team_messages")).content.decode()
        assert SHARED_CSS in auth_client.get(reverse("feedback_thread", args=[thread.slug])).content.decode()

    def test_blocked_list_query_count_is_flat(self, auth_client, user, django_assert_max_num_queries):
        for _ in range(8):
            f.block(user, f.make_user(username=f.unique("bl_")))
        with django_assert_max_num_queries(12):
            auth_client.get(reverse("blocked_users"))

    def test_reports_list_query_count_is_flat(self, auth_client, user, django_assert_max_num_queries):
        for _ in range(8):
            f.make_report(user)
        with django_assert_max_num_queries(10):
            auth_client.get(reverse("my_reports"))


class TestTeamTextIsPlain:
    @pytest.mark.parametrize("stored, shown", [
        ("<div>jsp frero</div>", "jsp frero"),
        ("<p>Bonjour</p><p>Merci&nbsp;!</p>", "Bonjour\nMerci !"),
        ("Ligne 1<br>Ligne 2", "Ligne 1\nLigne 2"), ("A<br><br><br><br>B", "A\n\nB"),
        ("<script>alert(1)</script>Texte", "alert(1)Texte"),
        ("&lt;b&gt;littéral&lt;/b&gt;", "<b>littéral</b>"),
        ("  Plusieurs   espaces  ", "Plusieurs espaces"),
        ("Ligne A\n\nLigne B", "Ligne A\n\nLigne B"),
        ("", ""), (None, ""),
    ])
    def test_plain_text(self, stored, shown):
        from app.services.threads import plain_text
        assert plain_text(stored) == shown

    def test_legacy_html_decision_is_shown_as_clean_text(self, auth_client, user):
        f.make_report(user, admin_response="<div>jsp frero</div>")
        html = auth_client.get(reverse("my_reports")).content.decode()
        assert "jsp frero" in html and "&lt;div&gt;" not in html and "<div>jsp" not in html

    def test_literal_markup_left_in_the_text_stays_inert(self, auth_client, user):
        f.make_report(user, admin_response="&lt;script&gt;alert(1)&lt;/script&gt;")
        html = auth_client.get(reverse("my_reports")).content.decode()
        assert "<script>alert(1)" not in html

    def test_admin_form_stores_plain_text_only(self, user):
        from app.forms import ReportAdminForm
        form = ReportAdminForm({"status": "resolved", "admin_response": "<div>Décision&nbsp;prise</div>"}, instance=f.make_report(user))
        assert form.is_valid() and form.cleaned_data["admin_response"] == "Décision prise"

    def test_admin_form_uses_a_plain_textarea(self):
        from app.forms import ReportAdminForm
        widget = ReportAdminForm().fields["admin_response"].widget
        assert widget.__class__.__name__ == "Textarea"
