"""Page et API de la recherche unique : onglets, rubriques, droits, chargement progressif, échappement."""
import pytest
from django.urls import reverse

from app.models import Brewery
from tests import factories as f

pytestmark = pytest.mark.django_db

PAGE, API = reverse("all_beers"), reverse("api_search")


def results(client, **params):
    return client.get(PAGE, params).context


class TestPage:
    def test_one_bar_and_five_tabs_without_an_overview_tab(self, auth_client):
        html = auth_client.get(PAGE).content.decode()
        for label in ("Bières", "Brasseries", "Bars", "Près de moi", "Membres"):
            assert f">{label}</a>" in html
        assert ">Tout</a>" not in html and html.count('type="search"') == 1 and 'id="search-form"' in html

    def test_beers_are_the_default_tab(self, auth_client):
        assert results(auth_client)["active_tab"] == "bieres"

    def test_the_old_overview_tab_falls_back_to_beers(self, auth_client):
        assert results(auth_client, tab="tout")["active_tab"] == "bieres"

    def test_each_kind_is_found_in_its_own_tab(self, auth_client):
        f.make_beer(name="Soleil Blonde", brewery=f.make_brewery(name="Brasserie Soleil"))
        f.make_bar(name="Bar du Soleil")
        f.make_user(username="soleil_fan")
        assert [b.name for b in results(auth_client, q="soleil")["beers"]] == ["Soleil Blonde"]
        assert [b.name for b in results(auth_client, q="soleil", tab="brasseries")["breweries"]] == ["Brasserie Soleil"]
        assert [b.name for b in results(auth_client, q="soleil", tab="bars")["bars"]] == ["Bar du Soleil"]
        assert [u.username for u in results(auth_client, q="soleil", tab="membres")["users"]] == ["soleil_fan"]

    def test_nothing_found_says_so(self, auth_client):
        assert "Aucun résultat" in auth_client.get(PAGE, {"q": "zzzzzz", "tab": "brasseries"}).content.decode()

    def test_without_a_query_members_are_the_recent_contributors(self, auth_client, other_user):
        f.make_beer(added_by=other_user)
        context = results(auth_client, tab="membres")
        assert [u.username for u in context["users"]] == ["bobby"] and not context["has_query"]


class TestTabs:
    @pytest.mark.parametrize("tab, key", [("bieres", "beers"), ("brasseries", "breweries"), ("bars", "bars"), ("membres", "users")])
    def test_each_tab_lists_its_own_kind(self, auth_client, other_user, tab, key):
        f.make_beer(name="Alpha", brewery=f.make_brewery(name="Alpha Brew"), added_by=other_user)
        f.make_bar(name="Alpha Bar")
        context = results(auth_client, tab=tab)
        assert context["active_tab"] == tab and context[key]

    def test_unknown_tab_falls_back_to_beers(self, auth_client):
        assert results(auth_client, tab="admin")["active_tab"] == "bieres"

    def test_legacy_member_parameter_opens_members(self, auth_client):
        assert results(auth_client, uq="bob")["active_tab"] == "membres"

    def test_beer_filters_and_sort_apply_on_the_beers_tab(self, auth_client):
        from decimal import Decimal
        f.make_beer(name="Légère", degree=Decimal("3.0"))
        f.make_beer(name="Forte", degree=Decimal("9.0"))
        assert [b.name for b in results(auth_client, tab="bieres", degree="strong")["beers"]] == ["Forte"]
        assert [b.name for b in results(auth_client, tab="bieres", sort="name_asc")["beers"]] == ["Forte", "Légère"]

    def test_search_relevance_orders_beers_by_default(self, auth_client):
        f.make_beer(name="Super Stout Imperial")
        f.make_beer(name="Stout")
        assert [b.name for b in results(auth_client, tab="bieres", q="stout")["beers"]] == ["Stout", "Super Stout Imperial"]

    def test_breweries_come_with_their_beer_count(self, auth_client):
        brewery = f.make_brewery(name="Comptée")
        f.make_beer(brewery=brewery), f.make_beer(brewery=brewery), f.make_beer(brewery=brewery, is_deleted=True)
        assert results(auth_client, tab="brasseries", q="comptee")["breweries"][0].beer_count == 2

    def test_page_size_and_load_more_for_breweries_and_bars(self, auth_client):
        for _ in range(11):
            f.make_brewery(name=f.unique("Mousse ")), f.make_bar(name=f.unique("Mousse "))
        assert len(results(auth_client, tab="brasseries", q="mousse")["breweries"]) == 10
        for item_type in ("search_breweries", "search_bars"):
            body = auth_client.get(reverse("load_more_generic", args=[item_type]), {"q": "mousse", "offset": 10}).json()
            assert body["html"].count("Mousse") == 1 and body["has_more"] is False


class TestRights:
    def test_blocked_members_and_their_beers_are_hidden(self, auth_client, user, other_user):
        f.make_beer(name="Cachée Bloqué", added_by=other_user)
        f.block(user, other_user)
        assert not results(auth_client, q="cachee")["beers"]
        assert not results(auth_client, q="bobby", tab="membres")["users"]

    def test_suspended_members_are_hidden(self, auth_client):
        f.make_user(username="suspendu", is_active=False)
        assert not results(auth_client, q="suspendu", tab="membres")["users"]

    def test_deleted_beers_are_hidden(self, auth_client):
        f.make_beer(name="Supprimée", is_deleted=True)
        assert not results(auth_client, q="supprimee")["beers"]

    def test_search_requires_login(self, client):
        assert client.get(PAGE, {"q": "x"}).status_code == 302 and client.get(API).status_code == 302


class TestApi:
    def test_returns_the_results_block_only(self, auth_client):
        f.make_beer(name="Rapide")
        html = auth_client.get(API, {"q": "rapide"}).json()["html"]
        assert "Rapide" in html and 'role="tablist"' in html and "<html" not in html

    def test_same_content_as_the_page(self, auth_client):
        f.make_beer(name="Identique")
        assert "Identique" in auth_client.get(API, {"q": "identique", "tab": "bieres"}).json()["html"]

    def test_get_only(self, auth_client):
        assert auth_client.post(API).status_code == 405

    @pytest.mark.parametrize("payload", ["<script>alert(1)</script>", '"><img src=x onerror=alert(1)>'])
    def test_hostile_input_is_escaped_everywhere(self, auth_client, payload):
        for response in (auth_client.get(PAGE, {"q": payload}).content.decode(), auth_client.get(API, {"q": payload}).json()["html"]):
            assert payload not in response

    def test_a_huge_query_is_bounded(self, auth_client):
        assert auth_client.get(API, {"q": "mot " * 5000}).status_code == 200


class TestPlaceTargets:
    def test_a_located_place_opens_on_the_map_and_an_unlocated_one_on_its_page(self, auth_client):
        located = f.make_bar(name="Bar Carte", address="1 rue de la Carte, Paris")
        unlocated = f.make_bar(name="Bar Sans Adresse")
        by_name = {b.name: b.target_url for b in results(auth_client, tab="bars", q="bar")["bars"]}
        assert by_name["Bar Carte"] == f"/map/?kind=bar&place={located.slug}"
        assert by_name["Bar Sans Adresse"] == reverse("bar_detail", args=[unlocated.slug])

    def test_breweries_follow_the_same_rule(self, auth_client):
        brewery = f.make_brewery(name="Brasserie Carte", address="2 rue de la Brasserie, Lille")
        assert results(auth_client, q="carte", tab="brasseries")["breweries"][0].target_url == f"/map/?kind=brewery&place={brewery.slug}"
        body = auth_client.get(reverse("load_more_generic", args=["search_breweries"]), {"q": "carte"}).json()
        assert f"/map/?kind=brewery&amp;place={brewery.slug}" in body["html"]

    def test_the_map_knows_the_slug_of_every_marker(self, auth_client):
        bar = f.make_bar(name="Bar Marqueur", address="3 rue du Marqueur, Nantes")
        assert f'data-type="bar" data-slug="{bar.slug}"' in auth_client.get(reverse("map")).content.decode()


class TestNearby:
    def test_tab_is_a_shell_that_searches_nothing(self, auth_client):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            context = results(auth_client, tab="proche")
        assert context["nearby"] and "beers" not in context and "bars" not in context
        assert not [q for q in queries if any(table in q["sql"] for table in ("app_beer\"", "app_bar\"", "app_brewery\""))]

    def test_shell_and_privacy_notice_are_rendered(self, auth_client):
        html = auth_client.get(PAGE, {"tab": "proche"}).content.decode()
        assert "data-nearby" in html and reverse("api_places") in html and "ne la reçoit ni ne l'enregistre" in html

    def test_the_api_returns_public_fields_of_located_places_only(self, auth_client):
        f.make_bar(name="Bar Proche", address="4 rue Proche, Lyon", phone="0102030405", email="secret@example.test", siret="73282932000074")
        f.make_brewery(name="Brasserie Proche", address="5 rue Proche, Lyon")
        f.make_bar(name="Bar Fantôme")
        response = auth_client.get(API.replace("search", "places"))
        places = response.json()["places"]
        assert sorted(p["name"] for p in places) == ["Bar Proche", "Brasserie Proche"]
        assert set(places[0]) == {"kind", "kind_label", "name", "slug", "address", "image", "lat", "lng", "verified", "url"}
        for private in (b"secret@example.test", b"0102030405", b"73282932000074"):
            assert private not in response.content
        assert "private" in response["Cache-Control"] and "max-age=300" in response["Cache-Control"]

    def test_urls_are_site_relative(self, auth_client):
        f.make_bar(name="Bar Relatif", address="6 rue Relative, Lyon")
        assert all(p["url"].startswith("/") and not p["url"].startswith("//") for p in auth_client.get(reverse("api_places")).json()["places"])

    def test_the_api_requires_login_and_get(self, client, auth_client):
        assert client.get(reverse("api_places")).status_code == 302
        assert auth_client.post(reverse("api_places")).status_code == 405

    def test_the_position_is_never_part_of_any_request(self):
        from pathlib import Path
        source = Path("app/static/script/nearby.js").read_text()
        assert source.count("fetch(") == 1 and "fetch(url, { credentials: 'same-origin' })" in source
        assert "localStorage" not in source and "sessionStorage" not in source


class TestClientScriptsAreNotInjectable:
    @pytest.mark.parametrize("name", ["nearby.js", "recent_searches.js"])
    def test_untrusted_text_only_goes_through_textContent(self, name):
        from pathlib import Path
        source = Path(f"app/static/script/{name}").read_text()
        assert "innerHTML" not in source and "insertAdjacentHTML" not in source and "document.write" not in source and "eval(" not in source
        assert "textContent" in source

    def test_recent_searches_stay_on_the_device_and_per_account(self):
        from pathlib import Path
        source = Path("app/static/script/recent_searches.js").read_text()
        assert "fetch(" not in source and "XMLHttpRequest" not in source and "form.dataset.user" in source

    def test_the_page_wires_the_scripts_and_the_account_key(self, auth_client, user):
        html = auth_client.get(PAGE).content.decode()
        assert f'data-user="{user.pk}"' in html and 'id="recent-searches"' in html
        for script in ("nearby.js", "recent_searches.js", "search.js"):
            assert f"script/{script}" in html


def test_the_global_loader_ignores_events_already_handled_by_the_page():
    """Les onglets et le formulaire de recherche n'ouvrent pas de nouvelle page : le loader ne doit pas s'afficher (et rester)."""
    from pathlib import Path
    source = Path("app/static/script/loader.js").read_text()
    assert source.count("e.defaultPrevented") == 2
    assert source.index("e.defaultPrevented") < source.index("showLoader();", source.index("showLoader = "))


class TestPlaceCards:
    def test_places_use_the_same_card_as_the_nearby_template(self, auth_client):
        f.make_brewery(name="Brasserie Carte", address="2 rue de la Brasserie, Lille", is_verified=True)
        page = auth_client.get(PAGE, {"tab": "brasseries"}).content.decode()
        nearby = auth_client.get(PAGE, {"tab": "proche"}).content.decode()
        for hook in ("data-place-card", "data-name", "data-address", "data-kind-label", "data-verified", "data-distance", "data-image", "data-placeholder"):
            assert hook in page and hook in nearby
        assert "Brasserie Carte" in page and "0 bière" in page and "Vérifié" in page

    def test_the_card_hides_the_distance_until_nearby_fills_it(self, auth_client):
        f.make_bar(name="Bar Neutre")
        card = auth_client.get(PAGE, {"tab": "bars"}).content.decode()
        assert card.count("data-placeholder") == 1 and 'data-distance class="pointer-events-none badge badge-primary badge-sm shrink-0 hidden"' in card


def test_no_emoji_in_the_source_code():
    """Aucun emoji ni symbole décoratif (croix, flèches, coches) dans le code : les icônes sont des SVG, les libellés du texte."""
    import re
    from pathlib import Path
    emoji = re.compile("[\u2190-\u21FF\u2300-\u23FF\u25A0-\u25FF\u2600-\u27BF\u2800-\u28FF\u2B00-\u2BFF\U0001F000-\U0001FAFF]")
    offenders = [
        str(path) for root in ("app", "pokebeer") for path in Path(root).rglob("*")
        if path.suffix in {".py", ".html", ".txt", ".js", ".css"} and "migrations" not in path.parts and emoji.search(path.read_text(errors="ignore"))
    ]
    assert not offenders, offenders


class TestPlaceFiltersOnThePages:
    @pytest.fixture
    def places(self, user):
        f.make_bar(name="Bar Nantes", address="2 Quai de la Fosse, 44000 Nantes", is_verified=True)
        f.make_bar(name="Bar Lyon", address="1 rue A, 69000 Lyon", managers=[user])
        f.make_brewery(name="Brasserie Nantes", address="3 rue B, 44000 Nantes")
        f.make_brewery(name="Brasserie Lille", address="4 rue C, 59000 Lille")

    def test_bars_filtered_by_city_and_by_verification(self, auth_client, places):
        assert [b.name for b in results(auth_client, tab="bars", city="Nantes")["bars"]] == ["Bar Nantes"]
        assert [b.name for b in results(auth_client, tab="bars", verified="1")["bars"]] == ["Bar Nantes"]

    def test_filters_combine_with_the_search_text(self, auth_client, places):
        assert [b.name for b in results(auth_client, tab="bars", q="bar", city="lyon")["bars"]] == ["Bar Lyon"]
        assert results(auth_client, tab="bars", q="brasserie", city="lyon")["bars"] == []

    def test_the_panel_lists_the_cities_of_the_tab_and_offers_a_reset(self, auth_client, places):
        context = results(auth_client, tab="bars", city="Nantes")
        assert context["cities"] == ["Lyon", "Nantes"] and context["filtered"] and not context["is_brewery_tab"]
        html = auth_client.get(PAGE, {"tab": "bars", "city": "Nantes"}).content.decode()
        assert '<option value="Nantes" selected>' in html and "data-reset-filters" in html and 'name="verified"' in html
        assert 'name="style"' not in html and 'name="sort"' in html
        for removed in ('name="managed"', 'name="located"'):
            assert removed not in html

    def test_the_brewery_tab_adds_the_style_filter(self, auth_client, places):
        f.make_beer(brewery=Brewery.objects.get(name="Brasserie Lille"), style="Saison")
        context = results(auth_client, tab="brasseries", style="saison")
        assert [b.name for b in context["breweries"]] == ["Brasserie Lille"] and context["is_brewery_tab"]
        assert 'name="style"' in auth_client.get(PAGE, {"tab": "brasseries"}).content.decode()

    def test_places_can_be_sorted_like_beers(self, auth_client, places):
        assert [b.name for b in results(auth_client, tab="bars", sort="name_desc")["bars"]] == ["Bar Nantes", "Bar Lyon"]
        assert [b.name for b in results(auth_client, tab="bars", sort="date_desc")["bars"]] == ["Bar Lyon", "Bar Nantes"]
        assert [b.name for b in results(auth_client, tab="brasseries", sort="name_asc")["breweries"]] == ["Brasserie Lille", "Brasserie Nantes"]
        assert results(auth_client, tab="bars", sort="name_desc")["filtered"]

    def test_the_sort_survives_load_more_and_ignores_garbage(self, auth_client):
        for index in range(12):
            f.make_bar(name=f"Bar {index:02d}")
        page = auth_client.get(reverse("load_more_generic", args=["search_bars"]), {"sort": "name_desc", "offset": 10}).json()["html"]
        assert page.index("Bar 01") < page.index("Bar 00")
        assert results(auth_client, tab="bars", sort="'; DROP")["bars"]

    def test_no_reset_link_without_filters(self, auth_client, places):
        assert "data-reset-filters" not in auth_client.get(PAGE, {"tab": "bars", "q": "bar"}).content.decode()

    def test_load_more_keeps_the_filters(self, auth_client):
        for index in range(12):
            f.make_bar(name=f"Bar Nantes {index}", address=f"{index} rue A, 44000 Nantes")
        f.make_bar(name="Bar Lyon", address="1 rue A, 69000 Lyon")
        body = auth_client.get(reverse("load_more_generic", args=["search_bars"]), {"city": "Nantes", "offset": 10}).json()
        assert body["html"].count("data-place-card") == 2 and "Bar Lyon" not in body["html"]

    def test_the_other_tabs_have_no_place_filters(self, auth_client, places):
        assert "filter_template" not in results(auth_client, tab="membres")
        assert results(auth_client, tab="proche").get("filter_template") is None


def test_the_filter_panel_keeps_the_state_chosen_by_the_member():
    """Le bloc est remplacé à chaque filtre : le script doit relire l'état du panneau avant, et le remettre après."""
    from pathlib import Path
    source = Path("app/static/script/search.js").read_text()
    assert "input[data-filter-panel]" in source
    assert source.index("wasOpen = panel()") < source.index("results.innerHTML = data.html") < source.index("panel().checked = wasOpen")


def test_the_filter_panel_is_marked_on_every_filterable_tab(auth_client):
    for tab in ("bieres", "brasseries", "bars"):
        assert "data-filter-panel" in auth_client.get(PAGE, {"tab": tab}).content.decode()
    assert "data-filter-panel" not in auth_client.get(PAGE, {"tab": "membres"}).content.decode()
