"""Scanner d'étiquette en direct : mesures d'image (Node), câblage de la page et règles de sécurité du code client."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from django.urls import reverse

SCRIPTS = Path("app/static/script")
SCANNER_FILES = ("frame_metrics.js", "ean_decoder.js", "barcode_reader.js", "label_scan_client.js", "label_scanner.js", "label_scan_page.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
@pytest.mark.parametrize("script", ["frame_metrics_check.js", "ean_decoder_check.js"])
def test_pure_front_logic_behaves(script):
    result = subprocess.run(["node", f"tests/js/{script}"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr


@pytest.mark.django_db
class TestAddBeerPage:
    def test_the_page_wires_the_scanner_and_keeps_the_photo_fallback(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        assert 'id="label-scanner"' in html and 'role="dialog"' in html and 'aria-modal="true"' in html
        assert 'id="camera-input"' in html and 'id="scan-pick-photo"' in html and 'id="scan-status"' in html
        assert f'data-url="{reverse("analyze_label")}"' in html and f'data-ean-url="{reverse("lookup_ean")}"' in html and "style/label_scanner.css" in html
        positions = [html.index(f"script/{name}") for name in SCANNER_FILES]
        assert positions == sorted(positions)  # chaque module est chargé après ceux dont il dépend

    def test_the_guide_the_progress_bar_and_the_manual_button_exist(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        for hook in ("data-scanner-video", "data-scanner-message", "data-scanner-progress", "data-scanner-capture", "data-scanner-close", "label-scanner__guide"):
            assert hook in html
        assert "playsinline" in html and "muted" in html

    def test_the_status_line_is_announced_to_screen_readers(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        assert html.count('aria-live="polite"') >= 2

    def test_the_member_is_told_that_the_barcode_is_easier(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        assert html.count("code-barres (EAN)") >= 2 and "le plus rapide et le plus fiable" in html

    def test_the_scanned_code_travels_in_a_hidden_field_of_the_form(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        assert 'type="hidden" name="beer-ean"' in html and 'id="id_beer-ean"' in html

    def test_the_old_alert_based_flow_is_gone(self):
        assert "scan-loader" not in Path("app/templates/add_beer.html").read_text()
        assert "alert(" not in "".join((SCRIPTS / name).read_text() for name in SCANNER_FILES)


class TestSecurityOfTheClientCode:
    @pytest.mark.parametrize("name", SCANNER_FILES)
    def test_no_html_injection_primitives(self, name):
        source = (SCRIPTS / name).read_text()
        for forbidden in ("innerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            assert forbidden not in source

    def test_the_camera_is_video_only_and_always_stopped(self):
        source = (SCRIPTS / "label_scanner.js").read_text()
        assert "audio: false" in source and "getTracks().forEach(track => track.stop())" in source
        # le flux est coupé à la fermeture, quand la page est masquée ou quittée
        assert "visibilitychange" in source and "pagehide" in source and "Escape" in source

    def test_nothing_from_the_camera_is_stored_on_the_device(self):
        for name in SCANNER_FILES:
            source = (SCRIPTS / name).read_text()
            assert "localStorage" not in source and "sessionStorage" not in source and "indexedDB" not in source

    def test_the_only_network_call_is_the_csrf_protected_same_origin_post(self):
        sources = {name: (SCRIPTS / name).read_text() for name in SCANNER_FILES}
        assert sum(source.count("fetch(") for source in sources.values()) == 1  # un seul point de sortie, partagé par l'étiquette et le code-barres
        client = sources["label_scan_client.js"]
        assert "'X-CSRFToken': this.csrfToken" in client and "credentials: 'same-origin'" in client and "method: 'POST'" in client
        assert client.count("this.post(") == 2 and "https://" not in client  # aucune adresse extérieure : la base de produits n'est jamais appelée depuis le navigateur

    def test_barcodes_are_validated_in_the_browser_before_any_request(self):
        scanner = (SCRIPTS / "label_scanner.js").read_text()
        reader = (SCRIPTS / "barcode_reader.js").read_text()
        assert "EanDecoder.isValid(item.rawValue)" in reader and "Confirmer" in scanner and "rejectedCodes" in scanner and "MAX_BARCODE_LOOKUPS" in scanner

    def test_automatic_analyses_are_capped_to_protect_the_daily_quota(self):
        source = (SCRIPTS / "label_scanner.js").read_text()
        assert re.search(r"MAX_AUTO_ATTEMPTS = [1-3];", source) and "COOLDOWN_MS" in source and "SESSION_MS" in source

    def test_the_server_answer_only_fills_the_five_known_fields(self):
        client = (SCRIPTS / "label_scan_client.js").read_text()
        ids = re.findall(r"id: '(id_[a-z_-]+)'", client)
        assert ids == ["id_beer-name", "id_beer-brewery_name", "id_beer-style", "id_beer-degree", "id_beer-bitterness"]
        assert "String(value)" in client
