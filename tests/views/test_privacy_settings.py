"""Réglage de confidentialité : section réservée à l'application Android, script servi avec la page."""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_account_page_ships_the_hidden_privacy_section_and_script(auth_client):
    html = auth_client.get(reverse("account")).content.decode()
    assert 'id="privacy-settings" class="hidden' in html  # masquée tant que le pont Android n'existe pas
    assert 'id="analytics-consent"' in html and "script/analytics_consent.js" in html
    assert "Mesure d'audience" in html


def test_script_only_reveals_the_section_when_the_android_bridge_exists():
    from pathlib import Path
    source = Path("app/static/script/analytics_consent.js").read_text()
    assert "if (!bridge" in source and "section.classList.remove('hidden')" in source
    assert source.index("if (!bridge") < source.index("classList.remove('hidden')")
