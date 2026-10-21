"""Analytics des gérants : qui y accède, ce qu'ils voient, ce qu'ils ne voient jamais, exports et liens d'entrée."""
import html as htmllib
import zipfile
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from django.urls import reverse
from django.utils import timezone

from app.services.analytics import access
from app.services.analytics.bar_report import BarReport
from app.services.analytics.brewery_report import BreweryReport
from app.services.analytics.periods import Period
from app.services.protection.throttle import PRO_ANALYTICS_BY_USER
from tests import factories as f

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(geocoder):
    """Deux brasseries et deux bars (chacun avec son gérant), des dégustateurs, des lieux autour du bar A et un membre ordinaire."""
    brewer_a = f.make_user(username="brasseur_a", groups=("Brasseur",))
    brewer_b = f.make_user(username="brasseur_b", groups=("Brasseur",))
    barman_a = f.make_user(username="barman_a", groups=("Bartender",))
    brewery_a = f.make_brewery(name="Brasserie Alpha", managers=[brewer_a])
    brewery_b = f.make_brewery(name="Brasserie Bravo", managers=[brewer_b])
    bar_a = f.make_bar(name="Bar Alpha", address="Paris", managers=[barman_a])  # le géocodeur factice le place en 48.8566, 2.3522
    bar_b = f.make_bar(name="Bar Bravo", address="Lyon")
    beer_a = f.make_beer(name="Alpha IPA", brewery=brewery_a, style="IPA")
    beer_b = f.make_beer(name="Bravo Stout", brewery=brewery_b, style="Stout")
    today = timezone.localdate()
    drinkers = [f.make_user(username=f"buveur_{i}") for i in range(4)]
    for index, drinker in enumerate(drinkers):
        for beer in (beer_a, beer_b):
            drink = f.make_drink(drinker, beer, note=6 + index, date=today - timedelta(days=index * 20), venue_type="bar", company="friends",
                                 serving_format="pint", price=Decimal("5.50"))
            f.make_spot(drinker, drinks=[drink], latitude=48.8567, longitude=2.3523, date=today - timedelta(days=index))
    return {
        "brewer_a": brewer_a, "brewer_b": brewer_b, "barman_a": barman_a, "member": f.make_user(username="simple_membre"),
        "brewery_a": brewery_a, "brewery_b": brewery_b, "bar_a": bar_a, "bar_b": bar_b, "drinkers": drinkers,
    }


def url(kind, place, section=None):
    return reverse("pro_analytics_section", args=[kind, place.slug, section]) if section else reverse("pro_analytics_place", args=[kind, place.slug])


class TestAccessMatrix:
    def test_anonymous_is_sent_to_the_login(self, client, world, google_app):
        response = client.get(url("brewery", world["brewery_a"]))
        assert response.status_code == 302 and "login" in response.url

    @pytest.mark.parametrize("who, kind, place, status", [
        ("brewer_a", "brewery", "brewery_a", 200), ("brewer_a", "brewery", "brewery_b", 404), ("brewer_a", "bar", "bar_a", 404),
        ("barman_a", "bar", "bar_a", 200), ("barman_a", "bar", "bar_b", 404), ("barman_a", "brewery", "brewery_a", 404),
        ("member", "brewery", "brewery_a", 404), ("member", "bar", "bar_a", 404),
    ])
    def test_a_manager_reads_only_what_they_manage(self, client_for, world, who, kind, place, status):
        assert client_for(world[who]).get(url(kind, world[place])).status_code == status

    @pytest.mark.parametrize("kind, place", [("brewery", "brewery_a"), ("brewery", "brewery_b"), ("bar", "bar_a"), ("bar", "bar_b")])
    def test_the_team_reads_everything(self, client_for, staff, superuser, world, kind, place):
        assert client_for(staff).get(url(kind, world[place])).status_code == 200
        assert client_for(superuser).get(url(kind, world[place])).status_code == 200

    def test_a_manager_who_loses_the_role_loses_the_access(self, client_for, world):
        client = client_for(world["brewer_a"])
        assert client.get(url("brewery", world["brewery_a"])).status_code == 200
        world["brewery_a"].managers.remove(world["brewer_a"])
        assert client.get(url("brewery", world["brewery_a"])).status_code == 404

    def test_the_brewer_group_alone_gives_nothing(self, client_for, world):
        lone = f.make_user(username="brasseur_sans_fiche", groups=("Brasseur",))
        assert client_for(lone).get(url("brewery", world["brewery_a"])).status_code == 404

    @pytest.mark.parametrize("kind, slug", [("winery", "x"), ("brewery", "inconnue"), ("BREWERY", "x")])
    def test_unknown_kind_or_place_is_404(self, client_for, staff, kind, slug):
        assert client_for(staff).get(reverse("pro_analytics_place", args=[kind, slug])).status_code == 404

    def test_unknown_section_is_404(self, client_for, world):
        assert client_for(world["brewer_a"]).get(url("brewery", world["brewery_a"], "bar")).status_code == 404

    def test_a_brewery_section_is_not_a_bar_section(self, client_for, world):
        assert client_for(world["barman_a"]).get(url("bar", world["bar_a"], "beers")).status_code == 404

    def test_read_only(self, client_for, world):
        assert client_for(world["brewer_a"]).post(url("brewery", world["brewery_a"])).status_code == 405

    def test_a_suspended_account_has_no_access(self, world):
        world["brewer_a"].is_active = False
        assert not access.can_view(world["brewer_a"], world["brewery_a"]) and access.managed_places(world["brewer_a"]) == []

    def test_responses_are_never_cached(self, client_for, world):
        response = client_for(world["brewer_a"]).get(url("brewery", world["brewery_a"]))
        assert "no-store" in response.headers["Cache-Control"] and "private" in response.headers["Cache-Control"]


class TestIndex:
    def test_one_place_goes_straight_to_it(self, client_for, world):
        response = client_for(world["brewer_a"]).get(reverse("pro_analytics"))
        assert response.status_code == 302 and response.url == url("brewery", world["brewery_a"])

    def test_several_places_are_listed(self, client_for, world):
        world["bar_b"].managers.add(world["brewer_a"])
        html = client_for(world["brewer_a"]).get(reverse("pro_analytics")).content.decode()
        assert "Brasserie Alpha" in html and "Bar Bravo" in html and "Brasserie Bravo" not in html

    def test_an_ordinary_member_gets_an_explanation_not_data(self, client_for, world):
        html = client_for(world["member"]).get(reverse("pro_analytics")).content.decode()
        assert "réservées aux gérants" in html and "Alpha" not in html


class TestSections:
    @pytest.mark.parametrize("report, who, kind, place", [(BreweryReport, "brewer_a", "brewery", "brewery_a"), (BarReport, "barman_a", "bar", "bar_a")])
    def test_every_section_renders_for_the_manager(self, client_for, world, report, who, kind, place):
        for section in report.SECTIONS:
            response = client_for(world[who]).get(url(kind, world[place], section.key))
            assert response.status_code == 200, section.key
            assert section.title in htmllib.unescape(response.content.decode())

    def test_tabs_list_every_section_and_mark_the_current_one(self, client_for, world):
        html = htmllib.unescape(client_for(world["brewer_a"]).get(url("brewery", world["brewery_a"], "beers")).content.decode())
        assert all(section.title in html for section in BreweryReport.SECTIONS) and 'aria-current="true"' in html

    def test_charts_are_embedded_as_data_not_markup(self, client_for, world):
        html = client_for(world["brewer_a"]).get(url("brewery", world["brewery_a"])).content.decode()
        assert 'type="application/json"' in html and "script/pro_analytics.js" in html and "script/analytics_charts.js" in html

    def test_period_is_whitelisted(self, client_for, world):
        client = client_for(world["brewer_a"])
        for months in ("6", "999", "abc", "-3", "6; DROP TABLE"):
            assert client.get(url("brewery", world["brewery_a"]), {"months": months}).status_code == 200
        response = client.get(url("brewery", world["brewery_a"]), {"months": "999"})
        assert response.context["period"].months == Period.from_params({}).months

    def test_the_default_section_is_the_overview(self, client_for, world):
        response = client_for(world["brewer_a"]).get(url("brewery", world["brewery_a"]))
        assert response.context["section"].key == "overview"


class TestNothingLeaks:
    def test_a_brewery_page_never_shows_another_establishment_or_a_member(self, client_for, world):
        for section in BreweryReport.SECTIONS:
            html = client_for(world["brewer_a"]).get(url("brewery", world["brewery_a"], section.key)).content.decode()
            assert "Brasserie Bravo" not in html and "Bravo Stout" not in html
            assert not any(member.username in html or member.email in html for member in world["drinkers"])

    def test_a_bar_page_never_shows_another_bar_or_a_member(self, client_for, world):
        for section in BarReport.SECTIONS:
            html = client_for(world["barman_a"]).get(url("bar", world["bar_a"], section.key)).content.decode()
            assert "Bar Bravo" not in html and not any(member.username in html for member in world["drinkers"])

    def test_the_market_section_names_no_other_brewery(self, client_for, world):
        html = client_for(world["brewer_a"]).get(url("brewery", world["brewery_a"], "market")).content.decode()
        assert "Brasserie Bravo" not in html

    def test_small_groups_stay_hidden_from_the_manager(self, client_for, geocoder):
        brewer = f.make_user(username="brasseur_seul", groups=("Brasseur",))
        brewery = f.make_brewery(name="Petite", managers=[brewer])
        beer = f.make_beer(brewery=brewery, style="IPA")
        for _ in range(2):  # sous le seuil d'anonymat
            f.make_drink(f.make_user(username=f.unique("c_")), beer, price=Decimal("4.0"))
        response = client_for(brewer).get(url("brewery", brewery, "beers"))
        assert "masqué" in response.content.decode() and not response.context["tiles"]


class TestExport:
    def test_a_manager_exports_a_block_of_their_own_place(self, client_for, world):
        client = client_for(world["brewer_a"])
        response = client.get(url("brewery", world["brewery_a"], "beers"), {"export": "brewery-beers"})
        assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
        assert "Alpha IPA" in response.content.decode("utf-8-sig")
        assert "attachment" in response["Content-Disposition"] and "no-store" in response["Cache-Control"]

    def test_zip_of_a_section(self, client_for, world):
        response = client_for(world["brewer_a"]).get(url("brewery", world["brewery_a"], "beers"), {"export": "all"})
        assert response["Content-Type"] == "application/zip"
        assert zipfile.ZipFile(BytesIO(response.content)).namelist()

    def test_a_block_of_another_section_cannot_be_exported(self, client_for, world):
        client = client_for(world["brewer_a"])
        assert client.get(url("brewery", world["brewery_a"], "beers"), {"export": "brewery-trend"}).status_code == 404

    def test_exports_follow_the_same_access_rules(self, client_for, world):
        assert client_for(world["brewer_b"]).get(url("brewery", world["brewery_a"], "beers"), {"export": "all"}).status_code == 404

    def test_exports_are_neutralised_against_spreadsheet_formulas(self, client_for, world):
        f.make_beer(name="=HYPERLINK(\"http://x\")", brewery=world["brewery_a"], style="IPA")
        for drinker in world["drinkers"]:
            f.make_drink(drinker, world["brewery_a"].beer_set.get(name__startswith="="), note=5)
        response = client_for(world["brewer_a"]).get(url("brewery", world["brewery_a"], "beers"), {"export": "brewery-beers"})
        assert "'=HYPERLINK" in response.content.decode("utf-8-sig")


class TestThrottle:
    def test_too_many_requests_are_refused(self, client_for, world):
        for _ in range(PRO_ANALYTICS_BY_USER.attempts):
            PRO_ANALYTICS_BY_USER.record(world["brewer_a"].pk)
        assert client_for(world["brewer_a"]).get(url("brewery", world["brewery_a"])).status_code == 429


class TestEntryPoints:
    def test_profile_links_to_the_statistics(self, client_for, world):
        html = client_for(world["brewer_a"]).get(reverse("account")).content.decode()
        assert reverse("pro_analytics") in html

    def test_place_menu_shows_the_link_to_managers_only(self, client_for, world):
        manager = client_for(world["brewer_a"]).get(reverse("brewery_detail", args=[world["brewery_a"].slug])).content.decode()
        visitor = client_for(world["member"]).get(reverse("brewery_detail", args=[world["brewery_a"].slug])).content.decode()
        link = url("brewery", world["brewery_a"])
        assert link in manager and link not in visitor

    def test_bar_menu(self, client_for, world):
        assert url("bar", world["bar_a"]) in client_for(world["barman_a"]).get(reverse("bar_detail", args=[world["bar_a"].slug])).content.decode()


class TestReports:
    def test_section_keys_are_unique_and_documented(self):
        for report in (BreweryReport, BarReport):
            keys = [s.key for s in report.SECTIONS]
            assert len(keys) == len(set(keys)) and all(s.title and s.description for s in report.SECTIONS)

    def test_registry_covers_both_kinds(self):
        assert set(access.REPORTS) == {"brewery", "bar"}

    def test_all_sections_concatenate_without_repeating_the_same_note(self, world):
        brewery = f.make_brewery(name="Vide")
        blocks = BreweryReport(brewery, Period(12, "month")).blocks()
        texts = [b.text for b in blocks if b.block_type == "note"]
        assert len(texts) == len(set(texts))

    def test_one_section_matches_the_matching_part_of_the_full_report(self, world):
        report = BreweryReport(world["brewery_a"], Period(12, "month"))
        full_ids = [getattr(b, "id", None) for b in report.blocks()]
        assert [getattr(b, "id", None) for b in report.blocks("beers")] == [i for i in full_ids if i in ("brewery-beers", "brewery-style-share")]
