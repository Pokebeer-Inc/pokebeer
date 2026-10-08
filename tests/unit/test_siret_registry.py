"""Contrôle d'un SIRET dans l'annuaire des entreprises : ce qui est refusé, ce qui est seulement consigné, et la robustesse face à une réponse hostile."""
import pytest

from app.services import match_keys, siret_registry, upstream

SIRET = "73282932000074"


def company(**overrides):
    base = {
        "nom_complet": "BRASSERIE DU COIN", "activite_principale": "11.05Z",
        "siege": {"siret": SIRET, "etat_administratif": "A", "code_postal": "44000", "libelle_commune": "NANTES", "activite_principale": "11.05Z"},
    }
    return {**base, **overrides}


@pytest.fixture
def registry(monkeypatch):
    """Réponse de l'annuaire à simuler (state["payload"] : un dict, ou une exception à lever)."""
    state = {"payload": {"results": [company()]}}

    def get_json(url, params=None, timeout=None):
        if isinstance(state["payload"], Exception):
            raise state["payload"]
        return state["payload"]

    monkeypatch.setattr(upstream, "get_json", get_json)
    return state


class TestCheck:
    @pytest.fixture(autouse=True)
    def real(self, siret_directory):
        self.real_check = siret_directory.real

    def check(self, registry, payload=None, kind=match_keys.BREWERY, name="Brasserie du Coin", postal="44000"):
        if payload is not None:
            registry["payload"] = payload
        return self.real_check(SIRET, kind, name, postal)

    def test_a_valid_open_brewery(self, registry):
        result = self.check(registry)
        assert (result.found, result.active, result.activity_ok, result.postal_match, result.available) == (True, True, True, True, True)
        assert result.name == "BRASSERIE DU COIN" and result.city == "NANTES" and result.name_score == 1.0 and result.rejection is None

    def test_a_siret_that_does_not_exist_is_refused(self, registry):
        result = self.check(registry, {"results": []})
        assert not result.found and "n'existe pas" in result.rejection

    def test_a_closed_establishment_is_refused(self, registry):
        payload = {"results": [company(siege={"siret": SIRET, "etat_administratif": "F", "code_postal": "44000", "libelle_commune": "NANTES"})]}
        result = self.check(registry, payload)
        assert result.found and not result.active and "fermé" in result.rejection

    def test_a_secondary_establishment_is_found_among_the_matching_ones(self, registry):
        payload = {"results": [company(siege={"siret": "11111111111111", "etat_administratif": "A"}, matching_etablissements=[{"siret": SIRET, "etat_administratif": "A", "code_postal": "69001", "libelle_commune": "LYON"}])]}
        result = self.check(registry, payload)
        assert result.found and result.city == "LYON" and not result.postal_match

    def test_another_siret_in_the_answer_is_not_ours(self, registry):
        assert not self.check(registry, {"results": [company(siege={"siret": "99999999999999", "etat_administratif": "A"})]}).found

    def test_an_unrelated_activity_is_noted_not_refused(self, registry):
        result = self.check(registry, {"results": [company(activite_principale="62.01Z", siege={"siret": SIRET, "etat_administratif": "A", "code_postal": "44000", "activite_principale": "62.01Z"})]})
        assert result.found and result.active and not result.activity_ok and result.rejection is None

    def test_a_bar_accepts_drinking_place_codes(self, registry):
        payload = {"results": [company(activite_principale="56.30Z", siege={"siret": SIRET, "etat_administratif": "A", "code_postal": "44000", "activite_principale": "56.30Z"})]}
        assert self.check(registry, payload, kind=match_keys.BAR).activity_ok and not self.check(registry, payload, kind=match_keys.BREWERY).activity_ok

    def test_a_different_postal_code_and_name_are_noted(self, registry):
        result = self.check(registry, name="Tout autre chose", postal="75010")
        assert not result.postal_match and result.name_score < 0.5 and result.rejection is None

    def test_an_outage_never_blocks_the_registration(self, registry):
        result = self.check(registry, upstream.UpstreamUnavailable())
        assert not result.available and result.rejection is None and not result.found

    @pytest.mark.parametrize("payload", [None, [], "x", {"results": "x"}, {"results": [None, 5, "x"]}, {"results": [{"siege": "x"}]}, {"results": [{"siege": {"siret": SIRET, "etat_administratif": None}}]}])
    def test_odd_answers_never_crash(self, registry, payload):
        result = self.check(registry, payload)
        assert not result.found or result.active is False or result.available

    def test_hostile_text_is_cleaned(self, registry):
        payload = {"results": [company(nom_complet="<script>alert(1)</script> \U0001F37A" + "x" * 500)]}
        result = self.check(registry, payload)
        assert "<" not in result.name and len(result.name) <= 150

    def test_the_snapshot_is_plain_data(self, registry):
        snapshot = self.check(registry).as_dict()
        assert snapshot["siret"] == SIRET and set(snapshot) >= {"found", "active", "activity_ok", "postal_match", "available"}
