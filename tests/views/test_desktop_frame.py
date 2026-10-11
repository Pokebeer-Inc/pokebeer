"""Version ordinateur : l'application garde sa présentation mobile dans une colonne ; l'administration garde sa vue normale."""
from pathlib import Path

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

CSS = Path("app/static/style/frame.css").read_text()


class TestFrame:
    def test_every_page_of_the_app_loads_the_frame_stylesheet(self, auth_client):
        for name in ("index", "map", "notebook", "account"):
            assert "style/frame.css" in auth_client.get(reverse(name)).content.decode()

    def test_the_login_page_gets_it_too(self, client, google_app):
        assert "style/frame.css" in client.get(reverse("login")).content.decode()

    def test_the_admin_keeps_its_normal_desktop_view(self, client_for, superuser):
        html = client_for(superuser).get(reverse("admin:index")).content.decode()
        assert "style/frame.css" not in html and "pb-frame-fixed" not in html

    def test_nothing_changes_on_phones(self):
        assert CSS.index("@media (min-width: 768px)") < CSS.index("body {") and CSS.count("@media") == 1
        import re
        outside = re.sub(r"/\*.*?\*/", "", CSS.split("@media (min-width: 768px)")[0], flags=re.S).strip()
        assert outside == ":root { --pb-frame: 430px; --pb-bands: #d9d3cb; }"  # seules des variables hors du cadre ordinateur

    def test_fixed_blocks_are_realigned_on_the_column(self, auth_client):
        html = auth_client.get(reverse("index")).content.decode()
        assert 'class="pb-frame-fixed fixed bottom-0' in html and "#chat-toggle" in CSS and "#chat-window" in CSS
        assert "pb-frame-fixed" in auth_client.get(reverse("map")).content.decode()

    def test_the_column_is_a_single_shared_width(self):
        assert CSS.count("--pb-frame:") == 1 and "430px" in CSS
