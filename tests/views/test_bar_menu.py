"""Carte d'un bar : droits, ajout (bière du catalogue ou nouvelle via l'assistant), prix et format, affichage public et statistiques."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from app.models import BarBeer, Beer, BeerDraft, Drinks
from app.services.analytics import menu_report
from app.services.analytics.bar_report import BarReport
from app.services.analytics.periods import Period
from app.services.establishments import menu
from app.services.protection.throttle import MENU_EDITS_BY_USER
from tests import factories as f

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(geocoder):
    manager = f.make_user(username="barman_carte", groups=("Bartender",))
    bar = f.make_bar(name="Le Zinc", address="Paris", managers=[manager])  # le géocodeur factice le place en 48.8566, 2.3522
    other_bar = f.make_bar(name="Autre Bar", address="Lyon")
    brewery = f.make_brewery(name="Brasserie Carte")
    ipa = f.make_beer(name="Houblon", brewery=brewery, style="IPA")
    stout = f.make_beer(name="Noire", brewery=brewery, style="Stout")
    blonde = f.make_beer(name="Blonde", brewery=brewery, style="Blonde")
    return {"manager": manager, "bar": bar, "other_bar": other_bar, "brewery": brewery, "ipa": ipa, "stout": stout, "blonde": blonde,
            "stranger": f.make_user(username="curieux")}


def url(name, bar, *extra):
    return reverse(name, args=[bar.slug, *extra])


class TestService:
    def test_adding_creates_a_line_and_is_idempotent(self, world):
        entry, created = menu.add(world["bar"], world["ipa"], world["manager"], Decimal("6.50"), "pint")
        again, created_again = menu.add(world["bar"], world["ipa"], world["manager"], Decimal("7.00"), "")
        assert created and not created_again and again.pk == entry.pk
        again.refresh_from_db()
        assert again.price == Decimal("7.00") and again.serving_format == "pint"  # un format non donné ne remplace pas l'ancien
        assert BarBeer.objects.count() == 1

    def test_adding_again_without_price_keeps_the_price(self, world):
        menu.add(world["bar"], world["ipa"], world["manager"], Decimal("6.50"), "pint")
        entry, _ = menu.add(world["bar"], world["ipa"], world["manager"])
        assert entry.price == Decimal("6.50")

    def test_removing_keeps_the_history_and_lets_the_beer_come_back(self, world):
        entry, _ = menu.add(world["bar"], world["ipa"], world["manager"])
        menu.remove(entry)
        assert not menu.entries(world["bar"]).exists() and BarBeer.objects.count() == 1
        menu.add(world["bar"], world["ipa"], world["manager"])
        assert BarBeer.objects.count() == 2 and menu.entries(world["bar"]).count() == 1

    def test_a_retired_catalogue_beer_is_refused_and_hidden(self, world):
        menu.add(world["bar"], world["stout"], world["manager"])
        Beer.objects.filter(pk=world["stout"].pk).update(is_deleted=True)
        world["stout"].refresh_from_db()
        assert not menu.entries(world["bar"]).exists()
        with pytest.raises(menu.MenuError):
            menu.add(world["bar"], world["stout"], world["manager"])

    def test_the_menu_has_a_size_limit(self, world, monkeypatch):
        monkeypatch.setattr(menu, "MAX_ACTIVE_ENTRIES", 1)
        menu.add(world["bar"], world["ipa"], world["manager"])
        with pytest.raises(menu.MenuError):
            menu.add(world["bar"], world["stout"], world["manager"])
        menu.add(world["bar"], world["ipa"], world["manager"], Decimal("5"))  # mettre à jour une ligne existante reste possible

    def test_two_active_lines_for_one_beer_are_impossible_in_the_database(self, world):
        from django.db import IntegrityError, transaction
        menu.add(world["bar"], world["ipa"], world["manager"])
        with pytest.raises(IntegrityError), transaction.atomic():
            BarBeer.objects.create(bar=world["bar"], beer=world["ipa"])

    def test_a_removed_line_does_not_block_a_new_one(self, world):
        entry = BarBeer.objects.create(bar=world["bar"], beer=world["ipa"], removed_at=timezone.now())
        BarBeer.objects.create(bar=world["bar"], beer=world["ipa"])
        assert entry.removed_at is not None

    def test_rights(self, world, staff, superuser):
        assert menu.can_manage(world["manager"], world["bar"]) and menu.can_manage(staff, world["bar"]) and menu.can_manage(superuser, world["bar"])
        assert not menu.can_manage(world["manager"], world["other_bar"]) and not menu.can_manage(world["stranger"], world["bar"])


class TestAccess:
    @pytest.mark.parametrize("name, args, method", [
        ("bar_menu", (), "get"), ("bar_menu_search", (), "get"), ("bar_menu_add", (), "post"),
    ])
    def test_a_stranger_gets_a_404(self, client_for, world, name, args, method):
        response = getattr(client_for(world["stranger"]), method)(url(name, world["bar"], *args))
        assert response.status_code == 404

    def test_a_manager_of_another_bar_gets_a_404(self, client_for, world):
        assert client_for(world["manager"]).get(url("bar_menu", world["other_bar"])).status_code == 404

    def test_update_and_remove_are_closed_to_strangers_and_scoped_to_the_bar(self, client_for, world):
        entry, _ = menu.add(world["bar"], world["ipa"], world["manager"])
        assert client_for(world["stranger"]).post(url("bar_menu_remove", world["bar"], entry.pk)).status_code == 404
        # une ligne d'un autre bar n'est jamais atteinte par l'adresse d'un bar dont on est gérant
        other, _ = menu.add(world["other_bar"], world["ipa"], world["manager"])
        assert client_for(world["manager"]).post(url("bar_menu_remove", world["bar"], other.pk)).status_code == 404
        other.refresh_from_db()
        assert other.removed_at is None

    def test_anonymous_is_sent_to_the_login(self, client, world, google_app):
        assert client.get(url("bar_menu", world["bar"])).status_code == 302

    def test_the_team_can_edit_any_menu(self, client_for, staff, world):
        assert client_for(staff).get(url("bar_menu", world["bar"])).status_code == 200

    def test_read_only_and_write_only_methods(self, client_for, world):
        client = client_for(world["manager"])
        assert client.post(url("bar_menu", world["bar"])).status_code == 405 and client.get(url("bar_menu_add", world["bar"])).status_code == 405


class TestPages:
    def test_search_marks_what_is_already_served(self, client_for, world):
        menu.add(world["bar"], world["ipa"], world["manager"])
        data = client_for(world["manager"]).get(url("bar_menu_search", world["bar"]), {"term": "hou"}).json()
        assert [(d["name"], d["on_menu"]) for d in data] == [("Houblon", True)]
        assert set(data[0]) == {"slug", "name", "brewery", "style", "on_menu"}

    def test_short_or_empty_search_returns_nothing(self, client_for, world):
        assert client_for(world["manager"]).get(url("bar_menu_search", world["bar"]), {"term": "h"}).json() == []

    def test_add_with_price_and_format(self, client_for, world):
        client = client_for(world["manager"])
        client.post(url("bar_menu_add", world["bar"]), {"beer": world["ipa"].slug, "price": "6.50", "serving_format": "pint"})
        entry = BarBeer.objects.get()
        assert (entry.price, entry.serving_format, entry.added_by) == (Decimal("6.50"), "pint", world["manager"])

    @pytest.mark.parametrize("data", [{"price": "-1"}, {"price": "1000"}, {"price": "abc"}, {"serving_format": "tonneau"}])
    def test_invalid_values_are_refused(self, client_for, world, data):
        client_for(world["manager"]).post(url("bar_menu_add", world["bar"]), {"beer": world["ipa"].slug, **data})
        assert not BarBeer.objects.exists()

    def test_unknown_beer_is_404(self, client_for, world):
        assert client_for(world["manager"]).post(url("bar_menu_add", world["bar"]), {"beer": "inconnue"}).status_code == 404

    def test_update_changes_and_clears(self, client_for, world):
        client = client_for(world["manager"])
        entry, _ = menu.add(world["bar"], world["ipa"], world["manager"], Decimal("6.50"), "pint")
        client.post(url("bar_menu_update", world["bar"], entry.pk), {"price": "7.20", "serving_format": "half"})
        entry.refresh_from_db()
        assert (entry.price, entry.serving_format) == (Decimal("7.20"), "half")
        client.post(url("bar_menu_update", world["bar"], entry.pk), {"price": "", "serving_format": ""})
        entry.refresh_from_db()
        assert entry.price is None and entry.serving_format == ""

    def test_remove(self, client_for, world):
        entry, _ = menu.add(world["bar"], world["ipa"], world["manager"])
        client_for(world["manager"]).post(url("bar_menu_remove", world["bar"], entry.pk))
        entry.refresh_from_db()
        assert entry.removed_at is not None

    def test_edits_are_throttled(self, client_for, world):
        for _ in range(MENU_EDITS_BY_USER.attempts):
            MENU_EDITS_BY_USER.record(world["manager"].pk)
        assert client_for(world["manager"]).post(url("bar_menu_add", world["bar"]), {"beer": world["ipa"].slug}).status_code == 429

    def test_management_page_lists_the_lines_and_the_new_beer_link(self, client_for, world):
        menu.add(world["bar"], world["ipa"], world["manager"], Decimal("6.5"), "pint")
        html = client_for(world["manager"]).get(url("bar_menu", world["bar"])).content.decode()
        assert "Houblon" in html and 'value="6.50"' in html and f"{reverse('add_beer')}?bar={world['bar'].slug}" in html

    def test_names_are_escaped(self, client_for, world):
        beer = f.make_beer(name="<img src=x onerror=alert(1)>", brewery=world["brewery"], style="IPA")
        menu.add(world["bar"], beer, world["manager"])
        assert "<img src=x" not in client_for(world["manager"]).get(url("bar_menu", world["bar"])).content.decode()


class TestPublicDisplay:
    def test_members_see_the_menu_without_the_manager_links(self, client_for, world):
        menu.add(world["bar"], world["ipa"], world["manager"], Decimal("6.5"), "pint")
        menu.add(world["bar"], world["stout"], world["manager"])
        html = client_for(world["stranger"]).get(reverse("bar_detail", args=[world["bar"].slug])).content.decode()
        assert "Houblon" in html and "6,50 €" in html and "Noire" in html and url("bar_menu", world["bar"]) not in html

    def test_the_manager_sees_the_management_link(self, client_for, world):
        html = client_for(world["manager"]).get(reverse("bar_detail", args=[world["bar"].slug])).content.decode()
        assert url("bar_menu", world["bar"]) in html and "Ajoutez les bières que vous servez" in html

    def test_a_beer_page_says_where_it_is_served(self, client_for, world):
        menu.add(world["bar"], world["ipa"], world["manager"])
        menu.add(world["other_bar"], world["ipa"], world["manager"])
        html = client_for(world["stranger"]).get(reverse("beer_detail", args=[world["ipa"].slug])).content.decode()
        assert "Servie dans 2 bars" in html and "Le Zinc" in html

    def test_a_removed_line_is_no_longer_shown(self, client_for, world):
        entry, _ = menu.add(world["bar"], world["ipa"], world["manager"])
        menu.remove(entry)
        html = client_for(world["stranger"]).get(reverse("beer_detail", args=[world["ipa"].slug])).content.decode()
        assert "Servie dans" not in html


class TestNewBeerFromTheMenu:
    DATA = {"beer-name": "Nouvelle Bière", "beer-brewery_name": "Brasserie Neuve", "beer-degree": "5.5", "beer-style": "ipa",
            "menu-price": "6.00", "menu-serving_format": "pint"}

    def test_the_assistant_hides_the_tasting_steps(self, client_for, world):
        html = client_for(world["manager"]).get(reverse("add_beer"), {"bar": world["bar"].slug}).content.decode()
        assert 'data-mode="menu"' in html and "À la carte" in html and "Ajouter à la carte" in html and "wizard-recap" in html  # le gérant relit avant d'envoyer
        assert "drink-comment" not in html and "drink-note" not in html and 'name="menu_bar"' in html

    def test_the_ordinary_assistant_is_unchanged(self, client_for, world):
        html = client_for(world["manager"]).get(reverse("add_beer")).content.decode()
        assert 'data-mode=""' in html and "drink-comment" not in html and "Ajouter la bière" in html and "menu_bar" not in html

    def test_a_stranger_cannot_use_the_menu_mode(self, client_for, world):
        client = client_for(world["stranger"])
        assert client.get(reverse("add_beer"), {"bar": world["bar"].slug}).status_code == 404
        assert client.post(reverse("add_beer"), {**self.DATA, "menu_bar": world["bar"].slug}).status_code == 404
        assert not Beer.objects.filter(name="Nouvelle Bière").exists()

    def test_posting_creates_the_beer_without_any_tasting_and_serves_it(self, client_for, world):
        response = client_for(world["manager"]).post(reverse("add_beer"), {**self.DATA, "menu_bar": world["bar"].slug})
        assert response.status_code == 302 and response.url == url("bar_menu", world["bar"])
        beer = Beer.objects.get(name="Nouvelle Bière")
        assert beer.style == "IPA" and beer.added_by == world["manager"] and not Drinks.objects.filter(beer=beer).exists()
        entry = BarBeer.objects.get(bar=world["bar"], beer=beer)
        assert (entry.price, entry.serving_format) == (Decimal("6.00"), "pint")

    def test_a_full_menu_creates_nothing(self, client_for, world, monkeypatch):
        monkeypatch.setattr(menu, "MAX_ACTIVE_ENTRIES", 0)
        response = client_for(world["manager"]).post(reverse("add_beer"), {**self.DATA, "menu_bar": world["bar"].slug})
        assert response.status_code == 200 and not Beer.objects.filter(name="Nouvelle Bière").exists()

    def test_a_possible_duplicate_is_still_detected(self, client_for, world):
        data = {**self.DATA, "beer-name": "Houblon", "beer-brewery_name": "Brasserie Carte", "menu_bar": world["bar"].slug}
        response = client_for(world["manager"]).post(reverse("add_beer"), data)
        assert response.status_code == 200 and Beer.objects.filter(name="Houblon").count() == 1

    def test_the_draft_is_not_resumed_in_menu_mode_and_is_cleared_after(self, client_for, world):
        BeerDraft.objects.create(user=world["manager"], data={"beer-name": "Brouillon"}, current_step=2)
        client = client_for(world["manager"])
        assert "Brouillon" not in client.get(reverse("add_beer"), {"bar": world["bar"].slug}).content.decode()
        client.post(reverse("add_beer"), {**self.DATA, "menu_bar": world["bar"].slug})
        assert not BeerDraft.objects.filter(user=world["manager"]).exists()


class TestDraftModes:
    def post(self, client, **data):
        return client.post(reverse("save_beer_draft"), data)

    def test_the_carte_step_validates_without_any_tasting_field(self, client_for, world):
        client = client_for(world["manager"])
        response = self.post(client, step="3", strict="1", mode="menu", **{"menu-price": "6.5", "beer-name": "X", "beer-brewery_name": "Y"})
        assert response.status_code == 200

    def test_the_carte_step_refuses_a_bad_price(self, client_for, world):
        response = self.post(client_for(world["manager"]), step="3", strict="1", mode="menu", **{"menu-price": "-3"})
        assert response.status_code == 400

    def test_the_ordinary_mode_has_two_steps_only(self, client_for, world):
        assert self.post(client_for(world["manager"]), step="2", strict="1", **{"beer-name": "X", "beer-degree": "5"}).status_code == 200
        assert self.post(client_for(world["manager"]), step="3", strict="1").status_code == 400  # ni avis ni vérification

    def test_unknown_mode_and_out_of_range_steps(self, client_for, world):
        client = client_for(world["manager"])
        assert self.post(client, step="1", strict="1", mode="hack").status_code == 400
        assert self.post(client, step="5", strict="0", mode="menu").status_code == 400
        assert self.post(client, step="4", strict="0", mode="menu").status_code == 204


@pytest.fixture
def busy_bar(world):
    """Un bar avec une carte de trois bières et des dégustations autour de lui (quatre membres : au-dessus du seuil d'anonymat)."""
    today = timezone.localdate()
    drinkers = [f.make_user(username=f"client_{i}") for i in range(4)]
    for index, drinker in enumerate(drinkers):
        for beer, note in ((world["ipa"], 7 + index % 2), (world["stout"], 6), (world["blonde"], 8)):
            drink = f.make_drink(drinker, beer, note=note, date=today - timedelta(days=index), serving_format="pint", price=Decimal("5.00"), venue_type="bar")
            f.make_spot(drinker, drinks=[drink], latitude=48.8567, longitude=2.3523, date=today - timedelta(days=index))
        drinker.wishlist_beers.add(world["ipa"])
    extra = f.make_beer(name="Saison Rare", brewery=world["brewery"], style="Saison")
    for drinker in drinkers[:3]:
        f.make_drink(drinker, extra, note=9, date=today)
        drinker.wishlist_beers.add(extra)
    menu.add(world["bar"], world["ipa"], world["manager"], Decimal("7.50"), "pint")
    menu.add(world["bar"], world["stout"], world["manager"], Decimal("3.00"), "half")
    return world, drinkers, extra


class TestMenuAnalytics:
    def blocks(self, world, insights=True):
        return BarReport(world["bar"], Period(12, "month")).blocks("menu", insights=insights)

    def by_id(self, blocks):
        return {b.id: b for b in blocks if hasattr(b, "id")}

    def test_no_menu_means_no_blocks_and_a_helpful_message(self, client_for, world):
        assert self.blocks(world) == []
        response = client_for(world["manager"]).get(reverse("pro_analytics_section", args=["bar", world["bar"].slug, "menu"]))
        assert response.status_code == 200 and "Votre carte est vide" in response.content.decode() and url("bar_menu", world["bar"]) in response.content.decode()

    def test_kpis(self, busy_bar):
        world, *_ = busy_bar
        kpis = {b.label: b.value for b in self.blocks(world) if b.block_type == "kpi"}
        assert kpis["Bières à la carte"] == 2 and kpis["Prix moyen à la carte"] == "5,25 €"

    def test_the_menu_table_compares_prices_in_the_same_format(self, busy_bar):
        world, *_ = busy_bar
        rows = {row[0]: row for row in self.by_id(self.blocks(world))["menu-beers"].rows}
        assert rows["Houblon"][2] == "7,50 € (pinte)" and rows["Houblon"][3] == "5,00 €" and rows["Houblon"][4] == "+50 %"
        # demi à 3 € : l'équivalent d'un demi payé 5 € la pinte est 2,50 €
        assert rows["Noire"][3] == "2,50 €" and rows["Noire"][4] == "+20 %"
        assert rows["Houblon"][6] == 4 and rows["Houblon"][7] == 4  # bue par 4 membres autour du bar, 4 souhaits

    def test_what_is_drunk_nearby_but_not_served_is_suggested(self, busy_bar):
        world, _drinkers, extra = busy_bar
        blocks = self.by_id(self.blocks(world))
        assert [r[0] for r in blocks["menu-missing-local"].rows] == ["Blonde"] and extra.name not in str(blocks["menu-missing-local"].rows)
        assert blocks["menu-missing-wished"].rows[0][0] == "Saison Rare"
        assert ["Blonde", 4] in blocks["menu-missing-styles"].rows

    def test_insights_are_written_for_the_manager(self, busy_bar):
        world, *_ = busy_bar
        texts = " ".join(b.text for b in self.blocks(world) if b.block_type == "insight")
        assert "2 bières" in texts and "Blonde" in texts and "Saison Rare" in texts and "au-dessus" in texts

    def test_insights_stay_out_of_the_admin_report(self, busy_bar):
        world, *_ = busy_bar
        assert not any(b.block_type == "insight" for b in self.blocks(world, insights=False))

    def test_small_groups_are_hidden(self, world):
        brewery = world["brewery"]
        beer = f.make_beer(name="Seule", brewery=brewery, style="IPA")
        menu.add(world["bar"], beer, world["manager"], Decimal("6"), "pint")
        for _ in range(menu_report.MIN_GROUP_SIZE - 1):
            member = f.make_user(username=f.unique("c_"))
            drink = f.make_drink(member, beer, note=9, price=Decimal("5"), serving_format="pint")
            f.make_spot(member, drinks=[drink], latitude=48.8567, longitude=2.3523)
        row = self.by_id(self.blocks(world))["menu-beers"].rows[0]
        assert row[3] == "—" and row[5] == "—" and row[6] == "—"  # ni prix, ni note, ni dégustations autour du bar sous le seuil

    def test_the_whole_section_renders_in_the_app(self, client_for, busy_bar):
        world, *_ = busy_bar
        response = client_for(world["manager"]).get(reverse("pro_analytics_section", args=["bar", world["bar"].slug, "menu"]))
        html = response.content.decode()
        assert response.status_code == 200 and "En bref" in html and "Ma carte" in html and "Gérer ma carte" in html

    def test_a_stale_menu_is_flagged(self, busy_bar):
        world, *_ = busy_bar
        BarBeer.objects.update(added_at=timezone.now() - timedelta(days=200))
        assert any(b.block_type == "insight" and "pas été complétée" in b.text for b in self.blocks(world))
