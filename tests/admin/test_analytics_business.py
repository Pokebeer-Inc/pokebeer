"""Pages d'analytics orientées métier : audience, consommation, engagement, professionnels, catalogue, prévisions, communauté, rapports."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from app.models import (
    AccountDeletion, ActivityDay, BeerDraft, CatalogMiss, PageView, CampaignRecipient, EmailCampaign, EstablishmentClaim, FeedbackMessage, ManagerInvitation, ModerationEntry,
    QuotaUsage,
)
from app.services.analytics import export, privacy, series
from app.services.analytics.custom import engine
from app.services.analytics.custom.catalog import CATALOG
from app.services.analytics.periods import Period
from app.services.analytics.profiles import AGE_BANDS, age_band, price_blocks
from app.services.analytics.registry import PAGES, PAGES_BY_KEY
from tests import factories as f

pytestmark = pytest.mark.django_db

NEW_PAGES = ["forecasts", "consumption", "audience", "engagement", "pros", "catalogue", "health"]


def by_id(blocks):
    """Blocs d'une page par identifiant (les notes, qui n'en ont pas, sont ignorées)."""
    return {block.id: block for block in blocks if hasattr(block, "id")}


def years_ago(years, extra_days=0):
    today = timezone.localdate()
    return today.replace(year=today.year - years) - timedelta(days=extra_days)


@pytest.fixture
def market(superuser, geocoder):
    """Une communauté de 6 membres (âges et genres variés) qui boivent dans des contextes différents sur 8 mois, avec prix, pouces et lieux."""
    managed = f.make_brewery(name="Brasserie Gérée", managers=[f.make_user(username=f.unique("boss_"), groups=("Brasseur",))], postal_code="69001")
    free = f.make_brewery(name="Brasserie Libre", postal_code="75011")
    bar = f.make_bar(name="Le Comptoir", address="Paris")  # le géocodeur factice le place en 48.8566, 2.3522
    beers = [
        f.make_beer(name="Houblon", brewery=managed, style="IPA, NEIPA", degree=6.5, bitterness=55, ean="3017620422003", is_verified=True),
        f.make_beer(name="Brune", brewery=managed, style="Stout", degree=7.5, bitterness=30),
        f.make_beer(name="Blonde", brewery=free, style="Lager", degree=4.8),
        f.make_beer(name="Blanche", brewery=free, style="ipa", degree=5.0),
    ]
    profiles = [(22, "femme"), (23, "femme"), (24, "femme"), (31, "homme"), (33, "homme"), (34, "homme")]
    members = [f.make_user(username=f.unique("m_"), birth_date=years_ago(age, 30), gender=gender) for age, gender in profiles]
    today = timezone.localdate()
    drinks = []
    for index, member in enumerate(members):
        for offset, beer in enumerate(beers):
            drinks.append(f.make_drink(
                member, beer, note=5 + (index + offset) % 5, date=today - timedelta(days=offset * 35 + index),
                venue_type=("bar", "bar", "bar", "home", "home", "home")[index], company=("friends", "alone")[offset % 2],
                serving_format=("pint", "half", "bottle", "can")[offset], price=Decimal("4.50") + offset, comment="Très bon" if index % 2 else ""))
    spots = [f.make_spot(member, drinks=[drinks[i * 4]], friends=[members[(i + 1) % 6]], latitude=48.8567, longitude=2.3523) for i, member in enumerate(members)]
    members[0].wishlist_beers.add(beers[0], beers[2])
    f.react(members[1], drinks[0])
    f.react(members[2], drinks[0], is_like=False)
    f.follow(members[0], members[1])

    claimant = f.make_user(username=f.unique("c_"))
    EstablishmentClaim.objects.create(brewery=free, claimant=claimant, siret="12345678901234", status="approved", decided_at=timezone.now())
    EstablishmentClaim.objects.create(bar=bar, claimant=members[0], siret="12345678901235")
    ManagerInvitation.objects.create(brewery=managed, invitee=members[1], status="pending")
    QuotaUsage.objects.create(user=members[0], day=today, scope="chat", count=4)
    QuotaUsage.objects.create(user=members[1], day=today, scope="label", count=2)
    f.make_notification(members[0], "follow", sender=members[1])
    BeerDraft.objects.create(user=members[2], current_step=2)
    report = f.make_report(members[0], reported_beer=beers[0])
    feedback = f.make_feedback(members[1])
    FeedbackMessage.objects.create(feedback=feedback, author_kind="team", body="Merci")
    ModerationEntry.objects.create(kind="beer", action="created", object_id=beers[0].pk, label="Houblon", reviewed_at=timezone.now())
    campaign = EmailCampaign.objects.create(subject="Hello", body="Corps", status="done")
    CampaignRecipient.objects.create(campaign=campaign, user=members[0], status="sent")
    AccountDeletion.objects.create(user_id=999, reason="inactivity", last_activity_at=timezone.now(), was_warned=True)
    for index, member in enumerate(members):  # visites : 4 membres venus aujourd'hui, 2 il y a 3 jours
        ActivityDay.objects.create(user=member, day=today if index < 4 else today - timedelta(days=3))
        ActivityDay.objects.create(user=member, day=today - timedelta(days=1))
    PageView.objects.create(kind="brewery", object_id=free.pk, day=today, views=9, visitors=5)
    PageView.objects.create(kind="brewery", object_id=managed.pk, day=today, views=4, visitors=2)
    PageView.objects.create(kind="beer", object_id=beers[0].pk, day=today, views=12, visitors=6)
    PageView.objects.create(kind="bar", object_id=bar.pk, day=today, views=7, visitors=4)
    CatalogMiss.objects.create(source="beer_search", key="gose framboise", day=today, count=4)
    CatalogMiss.objects.create(source="ean", key="3080216050079", day=today, count=1)
    return {"managed": managed, "free": free, "bar": bar, "members": members, "beers": beers, "report": report, "spots": spots}


class TestNewPagesRender:
    @pytest.mark.parametrize("page", NEW_PAGES)
    def test_page_renders_with_rich_data(self, client_for, staff, market, page):
        response = client_for(staff).get(reverse("admin_analytics", args=[page]))
        assert response.status_code == 200 and response.context["blocks"]

    @pytest.mark.parametrize("page", NEW_PAGES)
    @pytest.mark.parametrize("months", [3, 24])
    def test_page_renders_for_extreme_periods(self, client_for, staff, market, page, months):
        assert client_for(staff).get(reverse("admin_analytics", args=[page]), {"months": months, "granularity": "week"}).status_code == 200

    def test_every_page_is_declared_in_the_menu(self, settings):
        links = {str(item["link"]) for group in settings.UNFOLD["SIDEBAR"]["navigation"] for item in group["items"]}
        assert {reverse("admin_analytics", args=[page.key]) for page in PAGES} <= links

    def test_every_block_of_every_page_can_be_exported(self, market):
        period = Period(12, "month")
        for page in PAGES:
            blocks = page.build(period, {"brewery": market["managed"].slug, "bar": market["bar"].slug})
            assert export.to_zip(blocks)

    def test_empty_database_never_crashes(self, client_for, staff):
        for page in NEW_PAGES:
            assert client_for(staff).get(reverse("admin_analytics", args=[page])).status_code == 200

    def test_pages_are_closed_to_members(self, auth_client):
        for page in NEW_PAGES:
            assert auth_client.get(reverse("admin_analytics", args=[page])).status_code == 302


class TestAudience:
    def test_age_bands(self):
        today = date(2026, 6, 15)
        assert age_band(None, today) is None
        assert age_band(date(2002, 6, 16), today) == "Moins de 25 ans"   # 24 ans et 364 jours
        assert age_band(date(2001, 6, 15), today) == "25–34 ans"         # 25 ans pile
        assert age_band(date(1991, 6, 15), today) == "35–44 ans"         # 35 ans pile
        assert age_band(date(1970, 1, 1), today) == "55 ans et plus"

    def test_bands_cover_every_age_without_overlap(self):
        for age in range(120):
            matching = [label for low, high, label in AGE_BANDS if low <= age <= high]
            assert len(matching) == 1

    def test_published_segments_and_hidden_small_ones(self, market):
        blocks = {b.id: b for b in PAGES_BY_KEY["audience"].build(Period(12, "month"), {}) if b.block_type == "chart"}
        ages = blocks["audience-age"]
        # 3 membres de moins de 25 ans, 3 de 25 à 34 ans : les deux tranches sont publiables
        assert dict(zip(ages.categories, ages.series[0]["data"], strict=True)) == {"Moins de 25 ans": 3, "25–34 ans": 3}
        genders = blocks["audience-gender"]
        assert sorted(genders.series[0]["data"]) == [3, 3]

    def test_a_segment_below_the_threshold_is_never_shown(self, superuser, geocoder):
        brewery = f.make_brewery()
        beer = f.make_beer(brewery=brewery, style="IPA")
        for age in (22, 23, 24, 40):  # une seule personne de 35 à 44 ans
            f.make_drink(f.make_user(username=f.unique("m_"), birth_date=years_ago(age, 30), gender="homme"), beer)
        blocks = PAGES_BY_KEY["audience"].build(Period(12, "month"), {})
        ages = by_id(blocks).get("audience-age")
        assert ages is not None and "35–44 ans" not in ages.categories

    def test_exact_birth_dates_never_appear(self, client_for, staff, market):
        html = client_for(staff).get(reverse("admin_analytics", args=["audience"])).content.decode()
        for member in market["members"]:
            assert member.birth_date.isoformat() not in html and member.username not in html


class TestConsumption:
    def test_price_summary_is_exact(self, market):
        from app.models import Drinks
        blocks = price_blocks(Drinks.objects.all(), "p")
        kpis = {b.label: b.value for b in blocks if b.block_type == "kpi"}
        assert kpis["Prix moyen payé"] == "6,00 €"  # prix de 4,50 à 7,50 par pas de 1 : moyenne 6
        assert kpis["Prix médian payé"] == "6,00 €"

    def test_prices_are_withheld_below_the_group_threshold(self, superuser):
        from app.models import Drinks
        beer = f.make_beer(style="IPA")
        for _ in range(privacy.MIN_GROUP_SIZE - 1):
            f.make_drink(f.make_user(username=f.unique("m_")), beer, price=Decimal("5.00"))
        blocks = price_blocks(Drinks.objects.all(), "p")
        assert [b.block_type for b in blocks] == ["note"]

    def test_context_charts_group_by_label(self, market):
        blocks = {b.id: b for b in PAGES_BY_KEY["consumption"].build(Period(12, "month"), {}) if b.block_type == "chart"}
        assert "ctx-venue" in blocks and set(blocks["ctx-venue"].categories) == {"Bar", "Maison"}
        assert "price-by-format" in blocks and "coverage" in blocks
        coverage = dict(zip(blocks["coverage"].categories, blocks["coverage"].series[0]["data"], strict=True))
        assert coverage["Prix"] == 100.0 and coverage["Commentaire"] == 50.0

    def test_price_per_litre_uses_serving_volume(self, market):
        blocks = {b.id: b for b in PAGES_BY_KEY["consumption"].build(Period(12, "month"), {}) if b.block_type == "chart"}
        assert all(value > 0 for value in blocks["price-litre-by-venue"].series[0]["data"])


class TestForecasts:
    def test_band_surrounds_the_forecast(self):
        values = [10, 12, 14, 16, 18, 20, 22, 24, 5]
        low, high = series.forecast_band(values, 3)
        predicted = series.forecast(values, 3)
        assert all(lo <= p <= hi for lo, p, hi in zip(low, predicted, high, strict=True))

    def test_band_widens_with_the_horizon(self):
        values = [10, 14, 11, 16, 13, 18, 15, 20, 5]
        low, high = series.forecast_band(values, 4)
        widths = [h - lo for lo, h in zip(low, high, strict=True)]
        assert widths == sorted(widths)

    def test_no_band_without_history(self):
        assert series.forecast_band([1, 2, 3]) == ([], [])

    def test_trend_strength_distinguishes_a_line_from_noise(self):
        assert series.trend_strength([1, 2, 3, 4, 5, 6, 7]) == 1.0
        assert series.trend_strength([5, 1, 6, 2, 5, 1, 6]) < 0.2
        assert series.trend_strength([1, 2]) is None

    def test_default_chart_is_unchanged_without_band(self):
        period = Period(12, "month")
        values = list(range(len(period.buckets())))
        plain = series.trend_chart("t", "T", values, period)
        banded = series.trend_chart("t", "T", values, period, band=True)
        assert len(plain.series) == 3 and len(banded.series) == 5 and banded.dashed == [2, 3, 4]

    def test_forecast_starts_at_the_current_interval_and_joins_the_last_complete_one(self):
        period = Period(12, "month")
        values = [10 + 2 * i for i in range(len(period.buckets()) - 1)] + [3]  # le dernier intervalle est en cours : incomplet
        chart = series.trend_chart("t", "T", values, period, band=True)
        predicted = series.forecast(values)
        line = chart.series[2]["data"]
        count = len(values)
        assert len(chart.categories) == count + len(predicted) - 1 and all(len(s["data"]) == len(chart.categories) for s in chart.series)
        assert line[count - 2] == values[count - 2]            # part du dernier intervalle complet
        assert line[count - 1] == predicted[0]                 # puis l'intervalle en cours, à sa place
        assert chart.categories[count - 1] == period.label(period.buckets()[-1])

    def test_page_announces_short_history(self, market):
        blocks = PAGES_BY_KEY["forecasts"].build(Period(12, "month"), {})
        reliability = next(b for b in blocks if b.block_type == "kpi" and b.label == "Fiabilité des prévisions")
        assert reliability.value in {"Faible", "Moyenne"}


class TestProfessionals:
    def test_prospects_list_only_unmanaged_places(self, market):
        blocks = by_id(PAGES_BY_KEY["pros"].build(Period(12, "month"), {}))
        names = [row[0] for row in blocks["prospects-breweries"].rows]
        assert "Brasserie Libre" in names and "Brasserie Gérée" not in names

    def test_claims_are_summarised(self, market):
        kpis = {b.label: b.value for b in PAGES_BY_KEY["pros"].build(Period(12, "month"), {}) if b.block_type == "kpi"}
        assert kpis["Revendications en attente"] == 1 and kpis["Comptes brasseur"] == 1


class TestNewMeasures:
    def test_real_active_members_come_from_visit_days(self, market):
        kpis = {b.label: b.value for b in PAGES_BY_KEY["engagement"].build(Period(12, "month"), {}) if b.block_type == "kpi"}
        assert kpis["Actifs hier (DAU)"] == 6 and kpis["Actifs sur 7 jours (WAU)"] == 6 and kpis["Actifs sur 30 jours (MAU)"] == 6
        blocks = by_id(PAGES_BY_KEY["engagement"].build(Period(12, "month"), {}))
        assert "active-visits" in blocks and "retention-visits" in blocks

    def test_old_activity_kpis_give_way_to_dau_wau_mau_once_history_is_long_enough(self, market):
        labels = lambda: {b.label for b in PAGES_BY_KEY["engagement"].build(Period(12, "month"), {}) if b.block_type == "kpi"}  # noqa: E731
        assert "Actifs sur 7 jours (dernière visite)" in labels()  # moins de 30 jours de visites enregistrées
        ActivityDay.objects.create(user=market["members"][0], day=timezone.localdate() - timedelta(days=40))
        assert "Actifs sur 7 jours (dernière visite)" not in labels() and "Actifs sur 7 jours (WAU)" in labels()

    def test_most_viewed_pages_and_prospect_views(self, market):
        blocks = by_id(PAGES_BY_KEY["pros"].build(Period(12, "month"), {}))
        assert blocks["top-brewery-views"].rows[0][:2] == ["Brasserie Libre", 9]
        assert blocks["top-beer-views"].rows[0][0] == "Houblon"
        free = next(row for row in blocks["prospects-breweries"].rows if row[0] == "Brasserie Libre")
        assert free[-1] == 9

    def test_views_below_the_anonymity_threshold_are_masked(self, market):
        blocks = by_id(PAGES_BY_KEY["pros"].build(Period(12, "month"), {}))
        assert blocks["top-brewery-views"].rows[1][1:] == [privacy_hidden(), privacy_hidden()]  # 2 visiteurs : masqué

    def test_brewery_report_shows_its_views(self, market):
        blocks = by_id(PAGES_BY_KEY["places"].build(Period(12, "month"), {"brewery": market["free"].slug}))
        assert blocks["kpi-vues-fiche"].value == 9 and "brewery-views-trend" in blocks

    def test_bar_profile_shows_its_views(self, market):
        blocks = by_id(PAGES_BY_KEY["bars"].build(Period(12, "month"), {"bar": market["bar"].slug}))
        assert blocks["kpi-vues-fiche"].value == 7

    def test_catalogue_lists_unmet_demand_families_and_unknown_styles(self, market):
        f.make_beer(name="Mystère", brewery=market["free"], style="Zythos exotique")
        blocks = by_id(PAGES_BY_KEY["catalogue"].build(Period(12, "month"), {}))
        assert blocks["miss-terms"].rows[0] == ["Recherche de bière", "gose framboise", 4]
        assert "family-supply-demand" in blocks
        assert ["Zythos exotique", 1] in blocks["style-unrecognized"].rows

    def test_opposed_members_are_counted_on_the_audience_page(self, market):
        member = market["members"][0]
        member.demographic_stats = False
        member.save(update_fields=["demographic_stats"])
        blocks = by_id(PAGES_BY_KEY["audience"].build(Period(12, "month"), {}))
        assert blocks["kpi-opposes-aux-statistiques"].value == 1


def privacy_hidden():
    return f"< {privacy.MIN_GROUP_SIZE}"


class TestBreweryReport:
    def test_report_has_every_section_for_a_busy_brewery(self, market):
        blocks = by_id(PAGES_BY_KEY["places"].build(Period(12, "month"), {"brewery": market["managed"].slug}))
        for block_id in ("brewery-trend", "brewery-ratings", "brewery-beers", "brewery-style-share", "brewery-audience-age", "brewery-ctx-venue"):
            assert block_id in blocks, block_id
        beers = {row[0]: row for row in blocks["brewery-beers"].rows}
        assert set(beers) == {"Houblon", "Brune"} and beers["Houblon"][1] == 6 and beers["Houblon"][6] == 1  # un souhait sur Houblon

    def test_report_is_hidden_when_the_brewery_has_too_few_drinkers(self, superuser):
        brewery = f.make_brewery(name="Petite Brasserie")
        beer = f.make_beer(brewery=brewery, style="IPA")
        f.make_drink(f.make_user(username=f.unique("m_")), beer)
        blocks = PAGES_BY_KEY["places"].build(Period(12, "month"), {"brewery": brewery.slug})
        assert "brewery-beers" not in by_id(blocks)
        assert any(b.block_type == "note" and "dégustateurs distincts" in b.text for b in blocks)

    def test_page_renders_through_the_view(self, client_for, staff, market):
        response = client_for(staff).get(reverse("admin_analytics", args=["places"]), {"brewery": market["managed"].slug})
        assert response.status_code == 200 and b"Houblon" in response.content


class TestBarProfile:
    def test_bar_page_shows_visit_profile(self, market):
        blocks = by_id(PAGES_BY_KEY["bars"].build(Period(12, "month"), {"bar": market["bar"].slug}))
        assert "kpi-taille-moyenne-du-groupe" in blocks and blocks["kpi-taille-moyenne-du-groupe"].value == 2.0
        assert "bar-ctx-venue" in blocks


class TestCustomCatalogExtensions:
    @pytest.mark.parametrize("dataset", sorted(CATALOG))
    def test_every_dimension_and_measure_builds(self, market, dataset):
        """Chaque combinaison jeu de données × regroupement × mesure s'exécute sans erreur SQL, y compris les expressions calculées (âge, prix)."""
        definition = CATALOG[dataset]
        period = Period(12, "month")
        for dimension in definition.dimensions:
            for measure in definition.measures:
                chart = "line" if definition.dimensions[dimension].kind == "time" else "table"
                spec = {"dataset": dataset, "dimension": dimension, "measures": [measure], "chart": chart}
                block = engine.build_block(1, "Test", spec, period)
                assert block.block_type != "table" or block.columns != ["Tuile invalide"], (dataset, dimension, measure)

    def test_age_dimension_groups_without_exposing_birth_dates(self, market):
        spec = {"dataset": "drinks", "dimension": "age", "measures": ["count"], "chart": "table", "limit": 10, "sort": "value_desc"}
        block = engine.build_block(1, "Âge", spec, Period(12, "month"))
        assert {row[0] for row in block.rows} == {"Moins de 25 ans", "25–34 ans"}

    def test_gender_dimension_hides_small_groups(self, superuser):
        beer = f.make_beer(style="IPA")
        f.make_drink(f.make_user(username=f.unique("m_"), gender="femme"), beer)
        spec = {"dataset": "drinks", "dimension": "gender", "measures": ["count"], "chart": "table", "limit": 10, "sort": "value_desc"}
        assert engine.build_block(1, "Genre", spec, Period(12, "month")).rows == []
