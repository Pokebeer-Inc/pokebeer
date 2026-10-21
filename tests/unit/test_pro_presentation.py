"""Mise en forme des statistiques des gérants : tableaux, constats, évolutions."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from app.services.analytics import presentation
from app.services.analytics.bar_report import BarReport
from app.services.analytics.blocks import Insight, Table
from app.services.analytics.brewery_report import MIN_DELTA_BASE, BreweryReport
from app.services.analytics.periods import Period
from tests import factories as f

pytestmark = pytest.mark.django_db


class TestPresentTable:
    def table(self):
        return Table("t", "T", ["Bière", "Dégustations", "Écart", "Part de marché", "Note"],
                     [["Houblon", 12, "+0,29", "12,5 %", 7.5], ["Brune", "< 3", "-0,10", "40 %", "—"], ["Blonde", 4, "—", "8 %", 6.0]])

    def test_numbers_are_right_aligned_and_labels_are_not(self):
        presented = presentation.present(self.table())
        assert [numeric for _label, numeric in presented.columns] == [False, True, True, True, True]

    def test_gaps_are_coloured_by_sign(self):
        cells = [row[2] for row in presentation.present(self.table()).rows]
        assert [c.tone for c in cells] == ["up", "down", ""]

    def test_share_columns_get_a_bar(self):
        bars = [row[3].bar for row in presentation.present(self.table()).rows]
        assert bars == [12, 40, 8]

    def test_floats_use_the_french_comma_and_hidden_groups_stay_numeric(self):
        rows = presentation.present(self.table()).rows
        assert rows[0][4].text == "7,5" and rows[1][1].numeric and rows[1][1].text == "< 3"

    def test_a_text_column_is_not_mistaken_for_numbers(self):
        table = Table("t", "T", ["Style", "Verdict"], [["IPA", "En hausse nette"], ["Stout", "Stable"]])
        assert [numeric for _label, numeric in presentation.present(table).columns] == [False, False]

    def test_empty_table(self):
        presented = presentation.present(Table("t", "T", ["A", "B"], []))
        assert presented.rows == [] and len(presented.columns) == 2

    def test_cells_are_never_html(self):
        cell = presentation.present(Table("t", "T", ["A"], [["<script>alert(1)</script>"]])).rows[0][0]
        assert cell.text == "<script>alert(1)</script>"  # le gabarit l'échappe : la mise en forme ne transforme rien en balise


@pytest.fixture
def busy(geocoder):
    brewer = f.make_user(username="brasseur_busy", groups=("Brasseur",))
    brewery = f.make_brewery(name="Busy", managers=[brewer])
    beers = [f.make_beer(name=f"B{i}", brewery=brewery, style="IPA") for i in range(3)]
    today = timezone.localdate()
    for index in range(4):
        drinker = f.make_user(username=f"d_{index}")
        for beer in beers:
            f.make_drink(drinker, beer, note=7 + index % 2, date=today - timedelta(days=5), venue_type="bar", company="friends", serving_format="pint", price=Decimal("5.0"))
    return brewer, brewery


class TestInsights:
    def test_pro_report_carries_insights_the_admin_does_not(self, busy):
        _brewer, brewery = busy
        report = BreweryReport(brewery, Period(12, "month"))
        assert any(b.block_type == "insight" for b in report.blocks("overview", insights=True))
        assert not any(b.block_type == "insight" for b in report.blocks("overview"))
        assert not any(b.block_type == "insight" for b in report.blocks())

    def test_insights_are_plain_sentences_with_a_tone(self, busy):
        _brewer, brewery = busy
        for section in BreweryReport.SECTIONS:
            for block in BreweryReport(brewery, Period(12, "month")).blocks(section.key, insights=True):
                if isinstance(block, Insight):
                    assert block.text.endswith((".", ")")) and block.tone in {"good", "neutral", "warn"}

    def test_audience_section_describes_the_customers(self, busy):
        _brewer, brewery = busy
        texts = [b.text for b in BreweryReport(brewery, Period(12, "month")).blocks("audience", insights=True) if isinstance(b, Insight)]
        assert any("bar" in t for t in texts) and any("entre amis" in t for t in texts) and any("Prix moyen payé" in t for t in texts)

    def test_beer_section_names_the_best_beer(self, busy):
        _brewer, brewery = busy
        texts = [b.text for b in BreweryReport(brewery, Period(12, "month")).blocks("beers", insights=True) if isinstance(b, Insight)]
        assert any(t.startswith("Votre bière la mieux notée") for t in texts)

    def test_no_percentage_on_a_tiny_base(self, busy):
        _brewer, brewery = busy
        report = BreweryReport(brewery, Period(12, "month"))
        kpi = next(b for b in report.blocks("overview") if b.block_type == "kpi" and b.label == "Dégustations")
        assert kpi.delta is None  # rien sur la période précédente
        assert MIN_DELTA_BASE >= 3

    def test_evolution_needs_a_real_previous_period(self, busy):
        _brewer, brewery = busy
        today = timezone.localdate()
        beer = brewery.beer_set.first()
        for index in range(MIN_DELTA_BASE):  # de quoi former une période précédente exploitable
            f.make_drink(f.make_user(username=f"old_{index}"), beer, date=today - timedelta(days=400))
        period = Period(12, "month")
        report = BreweryReport(brewery, period)
        kpi = next(b for b in report.blocks("overview") if b.block_type == "kpi" and b.label == "Dégustations")
        assert kpi.delta is not None and kpi.delta > 0

    def test_page_shows_the_insights_and_folds_the_technical_notes(self, client_for, busy):
        brewer, brewery = busy
        html = client_for(brewer).get(reverse("pro_analytics_section", args=["brewery", brewery.slug, "audience"])).content.decode()
        assert "En bref" in html and "À propos de ces chiffres" in html and "pa-insight" in html


class TestEmptyState:
    def test_a_place_without_activity_explains_itself(self, client_for, geocoder):
        brewer = f.make_user(username="brasseur_vide", groups=("Brasseur",))
        brewery = f.make_brewery(name="Vide", managers=[brewer])
        response = client_for(brewer).get(reverse("pro_analytics_section", args=["brewery", brewery.slug, "audience"]))
        assert response.context["empty"] is True and "Pas encore assez de données" in response.content.decode()

    def test_a_bar_without_location_says_why(self, geocoder):
        bar = f.make_bar(name="Sans adresse")
        bar.latitude = bar.longitude = None
        notes = [b.text for b in BarReport(bar, Period(12, "month")).blocks("overview") if b.block_type == "note"]
        assert notes and "pas localisé" in notes[0]
