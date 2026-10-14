"""Pages de l'interface « Carnet » : réglages du profil, stats et recherche du carnet, contexte du tampon."""
from datetime import date

import pytest
from django.utils import timezone
from django.urls import reverse

from app.models import Drinks
from tests import factories as f

pytestmark = pytest.mark.django_db

SECTIONS = ("profile", "notifications", "privacy", "security", "team")


class TestProfileAndSettings:
    def test_profile_page_has_no_settings_only_a_gear_to_the_settings_page(self, auth_client):
        html = auth_client.get(reverse("account")).content.decode()
        assert reverse("account_settings_home") in html
        for section in SECTIONS:
            assert reverse("account_settings", args=[section]) not in html
        assert 'id="reglages"' not in html and "Supprimer mon compte" not in html and "Se déconnecter" not in html
        assert "modal_delete_account" not in html

    def test_settings_page_holds_every_section_logout_and_account_deletion(self, auth_client):
        html = auth_client.get(reverse("account_settings_home")).content.decode()
        for section in ("profile", "notifications", "privacy", "security", "team"):
            assert reverse("account_settings", args=[section]) in html
        assert "Se déconnecter" in html and "Supprimer mon compte" in html and "modal_delete_account" in html
        assert reverse("my_reports") in html and reverse("blocked_users") in html

    def test_settings_page_requires_a_login(self, client):
        assert client.get(reverse("account_settings_home")).status_code == 302

    def test_sub_pages_go_back_to_the_settings_page(self, auth_client):
        html = auth_client.get(reverse("account_settings", args=["profile"])).content.decode()
        assert f'href="{reverse("account_settings_home")}"' in html

    @pytest.mark.parametrize("section", SECTIONS)
    def test_each_settings_section_renders(self, auth_client, section):
        assert auth_client.get(reverse("account_settings", args=[section])).status_code == 200

    def test_unknown_settings_section_is_a_404(self, auth_client):
        assert auth_client.get("/account/settings/unknown/").status_code == 404

    def test_settings_require_a_login(self, client):
        assert client.get(reverse("account_settings", args=["profile"])).status_code == 302

    def test_saving_the_profile_returns_to_the_same_settings_page(self, auth_client, user):
        response = auth_client.post(
            reverse("account_settings", args=["profile"]),
            {"btn_profile": "", "username": user.username, "email": user.email, "bio": "Nouvelle bio"},
        )
        assert response.status_code == 302 and response.url == reverse("account_settings", args=["profile"])


class TestCarnet:
    def test_stats_are_plain_text_with_amertume_under_alcool_and_no_bars(self, auth_client, user):
        f.make_drink(user, f.make_beer(degree=6, bitterness=30, style="IPA"), note=8)
        response = auth_client.get(reverse("notebook"))
        html = response.content.decode()
        assert response.context["total_drinks"] == 1 and response.context["avg_note"] == 8
        assert response.context["active_tab"] == "tastings"
        assert "pb-gauge" not in html and "abv_percent" not in response.context
        assert html.index("Alcool</dt>") < html.index("Amertume</dt>") < html.index("Style préféré</dt>")
        assert "pb-chip is-primary" not in html  # le style préféré n'est plus une pastille colorée

    @pytest.mark.parametrize("legacy", ["carnet", "collections"])
    def test_legacy_tab_names_open_the_tastings_tab(self, auth_client, legacy):
        assert auth_client.get(reverse("notebook"), {"tab": legacy}).context["active_tab"] == "tastings"

    def test_the_tastings_tab_shows_only_the_collection_tiles_not_the_list(self, auth_client, user):
        f.make_drink(user, f.make_beer())
        notebook = f.make_notebook(user, title="Bières d'été")
        html = auth_client.get(reverse("notebook")).content.decode()
        assert "?tab=collections" not in html
        assert reverse("notebook_all") in html and reverse("notebook_detail", args=[notebook.slug]) in html
        assert "Créer une collection" in html
        assert 'id="carnet-form"' not in html and 'id="carnet-list"' not in html  # la liste vit à l'intérieur de chaque collection

    def test_collection_tiles_count_their_beers_in_one_query(self, auth_client, user, django_assert_max_num_queries):
        drink = f.make_drink(user, f.make_beer())
        for _ in range(6):
            f.make_notebook(user, drinks=[drink])
        with django_assert_max_num_queries(18):
            assert auth_client.get(reverse("notebook")).status_code == 200

    def test_collections_are_not_shown_on_the_other_tabs(self, auth_client, user):
        f.make_drink(user, f.make_beer())
        assert 'id="collections-title"' not in auth_client.get(reverse("notebook"), {"tab": "additions"}).content.decode()

    def test_unknown_tab_falls_back_to_tastings(self, auth_client):
        assert auth_client.get(reverse("notebook"), {"tab": "zzz"}).context["active_tab"] == "tastings"

    def test_fragment_searches_my_tastings_only(self, auth_client, user, other_user):
        f.make_drink(user, f.make_beer(name="Zythos Blonde"))
        f.make_drink(user, f.make_beer(name="Brune Absente"))
        f.make_drink(other_user, f.make_beer(name="Zythos Secrète"))
        html = auth_client.get(reverse("notebook_drinks_fragment"), {"q": "Zythos"}).content.decode()
        assert "Zythos Blonde" in html and "Brune Absente" not in html and "Secrète" not in html

    def test_fragment_sorts_by_rating(self, auth_client, user):
        low, high = f.make_beer(name="Faible"), f.make_beer(name="Brillante")
        f.make_drink(user, low, note=3, date=date(2024, 1, 2))
        f.make_drink(user, high, note=9, date=date(2024, 1, 1))
        drinks = auth_client.get(reverse("notebook_drinks_fragment"), {"sort": "note_desc"}).context["my_drinks"]
        assert [d.beer.name for d in drinks] == ["Brillante", "Faible"]

    def test_fragment_requires_a_login(self, client):
        assert client.get(reverse("notebook_drinks_fragment")).status_code == 302


class TestTastingContext:
    def test_context_fields_are_optional_and_saved(self, auth_client, user):
        beer = f.make_beer()
        auth_client.post(reverse("rate_beer", args=[beer.slug]), {
            "date": timezone.localdate().isoformat(), "note": 7, "comment": "Très bien",
            "venue_type": "bar", "company": "friends", "serving_format": "pint", "price": "6.50",
        })
        drink = Drinks.objects.get(drinker=user, beer=beer)
        assert (drink.venue_type, drink.company, drink.serving_format, str(drink.price)) == ("bar", "friends", "pint", "6.50")

    def test_editing_without_the_context_fields_keeps_them(self, auth_client, user):
        drink = f.make_drink(user, venue_type="home", company="alone", serving_format="can", price="3.20")
        auth_client.post(reverse("modify_rate_beer", args=[drink.slug]), {"date": timezone.localdate().isoformat(), "note": 9, "comment": "Mieux"})
        drink.refresh_from_db()
        assert (drink.venue_type, drink.company, drink.serving_format, str(drink.price), drink.note) == ("home", "alone", "can", "3.20", 9)

    def test_invalid_choice_is_refused(self, auth_client, user):
        beer = f.make_beer()
        auth_client.post(reverse("rate_beer", args=[beer.slug]), {"date": timezone.localdate().isoformat(), "comment": "x", "venue_type": "moon"})
        assert not Drinks.objects.filter(drinker=user, beer=beer).exists()

    def test_the_add_page_offers_every_field_across_its_steps(self, auth_client):
        html = auth_client.get(reverse("add_beer")).content.decode()
        for label in ("La bière", "Ses caractéristiques", "Description et photo", "Votre avis", "Le contexte", "Vérification", "Lieu", "Avec qui", "Format", "Commentaire"):
            assert label in html


class TestCarnetWishlistTab:
    def test_tab_lists_only_my_wishlisted_beers_with_the_tastings_layout(self, auth_client, user, beer):
        f.make_beer(name="Pas voulue")
        user.wishlist_beers.add(beer)
        response = auth_client.get(reverse("notebook"), {"tab": "to-taste"})
        html = response.content.decode()
        assert response.context["active_tab"] == "to-taste"
        assert [b.name for b in response.context["wishlist_beers"]] == ["Test IPA"]
        # même barre de recherche et de tri que « Dégustations », même conteneur de liste
        assert 'id="carnet-form"' in html and 'id="carnet-q"' in html and 'id="carnet-list"' in html
        assert reverse("notebook_wishlist_fragment") in html and 'aria-current="true"' in html
        assert "Pas voulue" not in html

    def test_tiles_share_the_structure_of_the_tasting_tiles(self, auth_client, user, beer):
        user.wishlist_beers.add(beer)
        gouter = auth_client.get(reverse("notebook"), {"tab": "to-taste"}).content.decode()
        f.make_drink(user, f.make_beer(name="Déjà bue"))
        tastings = auth_client.get(reverse("notebook_all")).content.decode()
        tile = "bg-white rounded-lg p-3 relative overflow-hidden flex flex-col shadow-sm border border-base-200"
        assert tile in gouter and tile in tastings

    def test_empty_wishlist_shows_an_invitation(self, auth_client):
        assert "Rien à goûter pour l&#x27;instant" in auth_client.get(reverse("notebook"), {"tab": "to-taste"}).content.decode() or \
            "Rien à goûter pour l'instant" in auth_client.get(reverse("notebook"), {"tab": "to-taste"}).content.decode()

    def test_fragment_searches_and_sorts_only_my_list(self, auth_client, user, other_user):
        mine_a = f.make_beer(name="Zeste Blonde", degree=5)
        mine_b = f.make_beer(name="Amber Zeste", degree=9)
        theirs = f.make_beer(name="Zeste Secrète")
        user.wishlist_beers.add(mine_a, mine_b)
        other_user.wishlist_beers.add(theirs)
        beers = auth_client.get(reverse("notebook_wishlist_fragment"), {"q": "Zeste", "sort": "degree_desc"}).context["wishlist_beers"]
        assert [b.name for b in beers] == ["Amber Zeste", "Zeste Blonde"]

    def test_recent_sort_follows_the_date_added_to_the_list(self, auth_client, user):
        first, second = f.make_beer(name="Ajoutée en premier"), f.make_beer(name="Ajoutée ensuite")
        user.wishlist_beers.add(second)  # créée après, mais ajoutée avant
        user.wishlist_beers.add(first)
        beers = auth_client.get(reverse("notebook_wishlist_fragment")).context["wishlist_beers"]
        assert [b.name for b in beers] == ["Ajoutée en premier", "Ajoutée ensuite"]

    def test_unknown_sort_falls_back_and_never_errors(self, auth_client, user, beer):
        user.wishlist_beers.add(beer)
        assert auth_client.get(reverse("notebook_wishlist_fragment"), {"sort": "DROP TABLE"}).status_code == 200

    def test_load_more_paginates_the_wishlist_tiles(self, auth_client, user):
        user.wishlist_beers.add(*[f.make_beer() for _ in range(12)])
        page = auth_client.get(reverse("notebook"), {"tab": "to-taste"})
        assert len(page.context["wishlist_beers"]) == 10 and page.context["page_full"]
        more = auth_client.get(reverse("load_more_generic", args=["wishlist_tiles"]), {"offset": 10}).json()
        assert more["html"].count("modalRate-") >= 2 and more["has_more"] is False

    def test_fragment_requires_a_login(self, client):
        assert client.get(reverse("notebook_wishlist_fragment")).status_code == 302


class TestCollectionPage:
    def url(self, user):
        return reverse("notebook_detail", args=[f.make_notebook(user).slug])

    def test_all_beers_page_has_search_one_filter_button_and_the_list(self, auth_client, user):
        f.make_drink(user, f.make_beer(name="Dans la liste"))
        response = auth_client.get(reverse("notebook_all"))
        html = response.content.decode()
        assert 'id="carnet-q"' in html and 'id="filters-sheet"' in html and "data-open-filters" in html
        assert "Dans la liste" in html and response.context["filter_count"] == 0

    def test_every_sort_is_offered_in_the_sheet(self, auth_client):
        html = auth_client.get(reverse("notebook_all")).content.decode()
        for value in ("date_desc", "date_asc", "note_desc", "note_asc", "name_asc", "name_desc", "style_asc", "degree_desc", "degree_asc", "ibu_desc", "ibu_asc"):
            assert f'name="sort" value="{value}"' in html

    def test_active_filters_are_counted_for_the_filter_button(self, auth_client, user):
        f.make_drink(user, f.make_beer(name="Forte IPA", degree=9, bitterness=60, style="IPA"), note=8)
        context = auth_client.get(reverse("notebook_all"), {"q": "forte", "degree": "strong", "ibu": "high", "style": "IPA", "rating_min": 7, "rating_max": 9, "sort": "note_desc"}).context
        assert [param for param, _ in context["filter_chips"]] == ["q", "degree", "ibu", "style", "rating"]
        assert context["filter_count"] == 4  # la recherche n'est pas comptée : elle a sa propre barre
        assert context["sort"] == "note_desc"
        assert [d.beer.name for d in context["my_drinks"]] == ["Forte IPA"]

    def test_default_rating_range_does_not_hide_tastings_without_a_note(self, auth_client, user):
        f.make_drink(user, f.make_beer(name="Sans note"), note=None)
        context = auth_client.get(reverse("notebook_all"), {"rating_min": 0, "rating_max": 10}).context
        assert [d.beer.name for d in context["my_drinks"]] == ["Sans note"] and context["filter_chips"] == []

    def test_narrow_rating_range_filters(self, auth_client, user):
        f.make_drink(user, f.make_beer(name="Basse"), note=3)
        f.make_drink(user, f.make_beer(name="Haute"), note=9)
        names = [d.beer.name for d in auth_client.get(reverse("notebook_all"), {"rating_min": 8}).context["my_drinks"]]
        assert names == ["Haute"]

    def test_garbage_parameters_are_ignored_safely(self, auth_client):
        context = auth_client.get(reverse("notebook_all"), {"sort": "x; DROP", "degree": "<script>", "rating_min": "abc", "rating_max": "99", "style": "x" * 500}).context
        assert context["sort"] == "date_desc" and context["rating_max"] == 10
        assert [param for param, _ in context["filter_chips"]] == ["style"] and len(context["filter_chips"][0][1]) <= 100

    def test_fragment_returns_the_list_with_an_out_of_band_counter(self, auth_client, user):
        f.make_drink(user, f.make_beer(name="Brune Douce", degree=4), note=7)
        f.make_drink(user, f.make_beer(name="Blonde Forte", degree=9), note=7)
        html = auth_client.get(reverse("notebook_drinks_fragment"), {"degree": "strong"}).content.decode()
        assert "Blonde Forte" in html and "Brune Douce" not in html
        assert 'hx-swap-oob="true"' in html and 'id="filter-count"' in html

    def test_load_more_keeps_the_search_and_filters(self, auth_client, user):
        for index in range(12):
            f.make_drink(user, f.make_beer(name=f"Forte {index}", degree=9))
        f.make_drink(user, f.make_beer(name="Légère", degree=3))
        page = auth_client.get(reverse("notebook_all"), {"degree": "strong", "sort": "name_asc"})
        assert page.context["page_full"] and "degree=strong" in page.context["querystring"] and "sort=name_asc" in page.context["querystring"]
        more = auth_client.get(reverse("load_more_generic", args=["notebook_drinks"]), {"degree": "strong", "sort": "name_asc", "offset": 10}).json()
        assert more["html"].count("Forte") >= 2 and "Légère" not in more["html"]

    def test_a_collection_page_shows_only_its_own_drinks(self, auth_client, user):
        inside, _outside = f.make_drink(user, f.make_beer(name="Dedans")), f.make_drink(user, f.make_beer(name="Dehors"))
        notebook = f.make_notebook(user, drinks=[inside])
        html = auth_client.get(reverse("notebook_drinks_fragment"), {"notebook_slug": notebook.slug}).content.decode()
        assert "Dedans" in html and "Dehors" not in html

    def test_another_members_collection_slug_leaks_nothing(self, auth_client, other_user):
        foreign = f.make_notebook(other_user, drinks=[f.make_drink(other_user, f.make_beer(name="Secrète"))])
        html = auth_client.get(reverse("notebook_drinks_fragment"), {"notebook_slug": foreign.slug}).content.decode()
        assert "Secrète" not in html
        assert auth_client.get(reverse("notebook_detail", args=[foreign.slug])).status_code == 404

    def test_the_filter_counter_is_hidden_without_filters(self, auth_client):
        html = auth_client.get(reverse("notebook_all")).content.decode()
        counter = html[html.index('id="filter-count"'):].split(">", 1)[0]
        assert "hidden" in counter and "inline-flex" not in counter


class TestProfileTopThreeAndBadges:
    def test_top_three_has_handles_for_filled_slots_and_no_helper_sentence(self, auth_client, user, beer):
        user.top_beer_1 = beer
        user.save()
        html = auth_client.get(reverse("account")).content.decode()
        assert "Touchez pour changer" not in html
        assert html.count("data-drag-handle") == 1  # une poignée par bière placée, les emplacements vides restent des squelettes
        assert html.count("data-open-top") == 3 and "Choisir une bière" in html
        assert 'data-url="' + reverse("reorder_top_beers") + '"' in html

    def test_trophy_page_has_a_back_button_to_the_profile(self, auth_client):
        html = auth_client.get(reverse("achievements")).content.decode()
        assert f'href="{reverse("account")}"' in html and "btn-circle btn-ghost" in html


class TestUsernameChange:
    def post(self, client, username, **extra):
        return client.post(reverse("update_username"), {"username": username}, HTTP_X_REQUESTED_WITH="fetch", **extra)

    def test_profile_shows_an_edit_button_and_dialog(self, auth_client, user):
        html = auth_client.get(reverse("account")).content.decode()
        assert "data-username-open" in html and 'id="modal_username"' in html and reverse("update_username") in html
        assert 'minlength="3"' in html and 'maxlength="30"' in html

    def test_valid_change_is_saved_and_returned(self, auth_client, user):
        response = self.post(auth_client, "Nouveau.Nom-1")
        assert response.status_code == 200 and response.json() == {"success": True, "username": "Nouveau.Nom-1"}
        user.refresh_from_db()
        assert user.username == "Nouveau.Nom-1"

    def test_the_public_profile_follows_the_new_name(self, auth_client, other_client, user):
        self.post(auth_client, "Renomme")
        assert other_client.get(reverse("public_profile", args=["Renomme"])).status_code == 200

    def test_the_session_survives_the_change(self, auth_client, user):
        self.post(auth_client, "Toujours.La")
        assert auth_client.get(reverse("account")).status_code == 200

    @pytest.mark.parametrize("bad", ["ab", "a" * 31, "avec espace", "accentué", "-commence", "<script>", "a/b", "ünï", "nul\x00", "a\nb", ""])
    def test_invalid_formats_are_refused_server_side(self, auth_client, user, bad):
        before = user.username
        response = self.post(auth_client, bad)
        assert response.status_code == 400 and response.json()["success"] is False and response.json()["error"]
        user.refresh_from_db()
        assert user.username == before

    def test_another_members_name_is_refused_whatever_the_case(self, auth_client, user, other_user):
        response = self.post(auth_client, other_user.username.upper())
        assert response.status_code == 400 and "déjà utilisé" in response.json()["error"]

    @pytest.mark.parametrize("reserved", ["admin", "Administrator", "support", "PokeBeer", "mon-pokebeer", "gaetan"])
    def test_reserved_names_are_refused(self, auth_client, reserved):
        response = self.post(auth_client, reserved)
        assert response.status_code == 400 and "réservé" in response.json()["error"]

    def test_only_the_case_of_my_own_name_can_change(self, auth_client, user):
        assert self.post(auth_client, user.username.upper()).json()["success"] is True
        user.refresh_from_db()
        assert user.username == user.username.upper()

    def test_keeping_the_same_name_does_not_use_up_a_change(self, auth_client, user):
        for _ in range(5):
            assert self.post(auth_client, user.username).status_code == 200

    def test_changes_are_limited_per_day(self, auth_client, user):
        for index in range(3):
            assert self.post(auth_client, f"Nom.numero{index}").status_code == 200
        response = self.post(auth_client, "Quatrieme.Nom")
        assert response.status_code == 429
        user.refresh_from_db()
        assert user.username == "Nom.numero2"

    def test_attempts_are_limited_so_free_names_cannot_be_probed(self, auth_client, other_user):
        for _ in range(10):
            assert self.post(auth_client, other_user.username).status_code == 400
        assert self.post(auth_client, other_user.username).status_code == 429

    def test_post_only_and_login_required(self, auth_client, client):
        assert auth_client.get(reverse("update_username")).status_code == 405
        assert client.post(reverse("update_username"), {"username": "Anonyme.Nom"}).status_code == 302

    def test_form_fallback_without_javascript_redirects_with_a_message(self, auth_client, user):
        response = auth_client.post(reverse("update_username"), {"username": "Sans.Js"})
        assert response.status_code == 302 and response.url == reverse("account")
        user.refresh_from_db()
        assert user.username == "Sans.Js"

    def test_a_member_cannot_rename_someone_else(self, auth_client, user, other_user):
        auth_client.post(reverse("update_username"), {"username": "Autre.Nom", "id": other_user.pk, "pk": other_user.pk}, HTTP_X_REQUESTED_WITH="fetch")
        other_user.refresh_from_db()
        assert other_user.username != "Autre.Nom"


class TestProfileEstablishments:
    def test_pro_members_see_their_establishments_with_links(self, client):
        pro = f.make_user(groups=["Bartender", "Brasseur"])
        brewery = f.make_brewery(name="Brasserie Gérée", managers=[pro])
        bar = f.make_bar(name="Bar Géré", managers=[pro])
        client.force_login(pro)
        response = client.get(reverse("account"))
        html = response.content.decode()
        assert 'id="establishments-title"' in html
        assert reverse("brewery_detail", args=[brewery.slug]) in html and reverse("bar_detail", args=[bar.slug]) in html
        assert "Brasserie Gérée" in html and "Bar Géré" in html
        assert html.index('id="establishments-title"') < html.index('id="succes-title"') < html.index('id="top3-title"')

    def test_a_pro_role_without_establishment_gets_an_empty_message(self, client):
        client.force_login(f.make_user(groups=["Bartender"]))
        html = client.get(reverse("account")).content.decode()
        assert 'id="establishments-title"' in html and "ne gérez aucun établissement" in html

    def test_a_manager_without_a_pro_group_still_sees_what_he_manages(self, client):
        manager = f.make_user()
        f.make_bar(name="Bar Sans Groupe", managers=[manager])
        client.force_login(manager)
        assert "Bar Sans Groupe" in client.get(reverse("account")).content.decode()

    def test_regular_members_do_not_see_the_section(self, auth_client):
        assert 'id="establishments-title"' not in auth_client.get(reverse("account")).content.decode()

    def test_only_my_own_establishments_are_listed(self, client):
        pro = f.make_user(groups=["Bartender"])
        f.make_bar(name="Bar Des Autres", managers=[f.make_user()])
        client.force_login(pro)
        assert "Bar Des Autres" not in client.get(reverse("account")).content.decode()

    def test_the_profile_query_count_stays_bounded_for_a_pro(self, client, django_assert_max_num_queries):
        pro = f.make_user(groups=["Bartender", "Brasseur"])
        for _ in range(4):
            f.make_bar(managers=[pro])
            f.make_brewery(managers=[pro])
        client.force_login(pro)
        with django_assert_max_num_queries(45):
            assert client.get(reverse("account")).status_code == 200


class TestSettingsDetails:
    def test_privacy_section_links_to_the_privacy_policy(self, auth_client):
        html = auth_client.get(reverse("account_settings", args=["privacy"])).content.decode()
        assert f'href="{reverse("privacy_policy")}"' in html and "Lire notre politique de confidentialité" in html
        link = html[html.index(f'href="{reverse("privacy_policy")}"'):].split(">", 1)[0]
        assert 'target="_blank"' in link and 'rel="noopener noreferrer"' in link

    def test_privacy_policy_address_redirects_to_the_configured_document(self, auth_client, settings):
        settings.PRIVACY_POLICY_URL = "https://example.org/politique"
        response = auth_client.get(reverse("privacy_policy"))
        assert response.status_code == 302 and response.url == "https://example.org/politique"

    def test_policy_link_is_only_on_the_privacy_page(self, auth_client):
        assert reverse("privacy_policy") not in auth_client.get(reverse("account_settings", args=["profile"])).content.decode()


class TestProfileSectionOrder:
    def test_order_is_establishments_then_achievements_then_top_three(self, client):
        pro = f.make_user(groups=["Bartender"])
        f.make_bar(managers=[pro])
        client.force_login(pro)
        html = client.get(reverse("account")).content.decode()
        assert html.index('id="establishments-title"') < html.index('id="succes-title"') < html.index('id="top3-title"')

    def test_regular_members_get_achievements_then_top_three(self, auth_client):
        html = auth_client.get(reverse("account")).content.decode()
        assert html.index('id="succes-title"') < html.index('id="top3-title"')


class TestPublicProfileDesign:
    def url(self, member):
        return reverse("public_profile", args=[member.username])

    def test_follows_the_account_page_design_and_keeps_the_data(self, auth_client, other_user):
        beer = f.make_beer(name="Bière publique", degree=7, bitterness=40, style="IPA")
        f.make_drink(other_user, beer, note=9)
        other_user.top_beer_1 = beer
        other_user.bio = "Amateur de houblon"
        other_user.save()
        response = auth_client.get(self.url(other_user))
        html = response.content.decode()
        for needle in (other_user.username, "Amateur de houblon", "Abonnés", "Abonnements", "Dégustées", "Son top 3", "Ses succès",
                       "Bière publique", "note moyenne", "Alcool", "Amertume", "Style préféré", "S'abonner"):
            assert needle in html
        assert response.context["total_drinks"] == 1
        assert "pb-card" in html and "tab-btn" not in html and "switchTab" not in html
        assert html.index('id="succes-title"') < html.index('id="top3-title"')

    def test_follow_button_switches_when_following(self, auth_client, user, other_user):
        f.follow(user, other_user)
        html = auth_client.get(self.url(other_user)).content.decode()
        assert "Ne plus suivre" in html and "S'abonner" not in html

    def test_report_and_block_stay_available(self, auth_client, other_user):
        html = auth_client.get(self.url(other_user)).content.decode()
        assert "modal_report_user" in html and "modal_block_user" in html and reverse("block_user", args=[other_user.username]) in html

    def test_a_back_button_leads_to_the_previous_page_on_this_site(self, auth_client, other_user):
        response = auth_client.get(self.url(other_user), HTTP_REFERER="http://testserver" + reverse("map"))
        assert response.context["back_url"] == "http://testserver" + reverse("map")

    def test_the_back_button_never_points_to_the_profile_itself_or_to_another_site(self, auth_client, other_user):
        own = auth_client.get(self.url(other_user), HTTP_REFERER="http://testserver" + self.url(other_user) + "?tab=additions")
        assert own.context["back_url"] == reverse("index")
        foreign = auth_client.get(self.url(other_user), HTTP_REFERER="https://evil.example/phish")
        assert foreign.context["back_url"] == reverse("index")

    def test_tastings_tab_is_the_default_and_loads_no_added_beers(self, auth_client, other_user):
        f.make_drink(other_user, f.make_beer(name="Bue par lui"))
        f.make_beer(name="Ajoutée par lui", added_by=other_user)
        response = auth_client.get(self.url(other_user))
        html = response.content.decode()
        assert response.context["active_tab"] == "tastings" and "Bue par lui" in html
        assert response.context["user_added_beers"] == [] and "Ajoutée par lui" not in html

    def test_added_beers_tab_loads_only_its_own_list(self, auth_client, other_user):
        f.make_drink(other_user, f.make_beer(name="Bue par lui"))
        f.make_beer(name="Ajoutée par lui", added_by=other_user)
        response = auth_client.get(self.url(other_user), {"tab": "additions"})
        html = response.content.decode()
        assert response.context["active_tab"] == "additions" and "Ajoutée par lui" in html
        assert response.context["user_drinks"] == [] and "Bue par lui" not in html

    def test_unknown_tab_falls_back_to_tastings(self, auth_client, other_user):
        assert auth_client.get(self.url(other_user), {"tab": "<script>"}).context["active_tab"] == "tastings"

    def test_establishments_are_shown_only_when_the_member_allows_it(self, auth_client):
        pro = f.make_user(groups=["Bartender"])
        f.make_bar(name="Bar Public", managers=[pro])
        assert "Bar Public" in auth_client.get(self.url(pro)).content.decode()
        pro.show_establishments = False
        pro.save()
        html = auth_client.get(self.url(pro)).content.decode()
        assert "Bar Public" not in html and 'id="establishments-title"' not in html

    def test_badges_are_not_links_to_my_own_trophy_page(self, auth_client, other_user):
        f.make_drink(other_user, f.make_beer())
        html = auth_client.get(self.url(other_user)).content.decode()
        assert f'href="{reverse("achievements")}"' not in html

    def test_blocked_members_stay_unreachable(self, auth_client, user, other_user):
        f.block(user, other_user)
        response = auth_client.get(self.url(other_user))
        assert response.status_code == 302 and response.url == reverse("index")

    def test_query_count_is_bounded(self, auth_client, other_user, django_assert_max_num_queries):
        for _ in range(6):
            f.make_drink(other_user, f.make_beer())
        with django_assert_max_num_queries(45):
            assert auth_client.get(self.url(other_user)).status_code == 200


class TestServingFormatVolumes:
    """Les volumes de la bouteille et de la canette sont précisés partout : choix des formulaires, fenêtres de notation et résumé."""

    def test_the_volumes_are_part_of_the_labels(self):
        from app.models import Drinks
        labels = dict(Drinks.ServingFormat.choices)
        assert labels["bottle"] == "Bouteille 75 cl" and labels["can"] == "Canette 33 cl"

    def test_the_add_page_and_the_rating_modal_offer_them(self, auth_client, user, beer):
        add = auth_client.get(reverse("add_beer")).content.decode()
        modal = auth_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()
        for html in (add, modal):
            assert "Bouteille 75 cl" in html and "Canette 33 cl" in html

    def test_the_tasting_summary_shows_them(self, auth_client, user, beer):
        f.make_drink(user, beer, note=7, serving_format="can")
        assert "Canette 33 cl" in auth_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()


class TestTastingModal:
    """Noter une bière (étape par étape) et modifier un avis (deux étapes) : croix de fermeture, mêmes champs, validation du serveur."""

    def new_modal(self, auth_client, beer):
        html = auth_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()
        modal = html[html.index(f'<dialog id="modalRate-{beer.slug}"'):]
        return modal[:modal.index("</dialog>")]

    def test_a_new_rating_goes_step_by_step_with_a_close_button(self, auth_client, beer):
        modal = self.new_modal(auth_client, beer)
        assert 'aria-label="Fermer"' in modal and "data-modal-close" in modal and "data-stepper" in modal
        assert [step for step in ("Votre note", "Votre avis", "Le contexte", "Format et prix") if f'data-title="{step}"' in modal] == [
            "Votre note", "Votre avis", "Le contexte", "Format et prix"]
        assert "data-stepper-back" in modal and "data-stepper-next" in modal and "data-stepper-submit" in modal and 'sur <span data-stepper-total>4</span>' in modal
        assert "Récapitulatif" not in modal  # l'envoi mène à la page de félicitations

    def test_every_field_of_the_tasting_form_is_still_sent_by_the_wizard(self, auth_client, beer):
        modal = self.new_modal(auth_client, beer)
        for name in ("date", "note", "comment", "photo", "venue_type", "company", "serving_format", "price"):
            assert f'name="{name}"' in modal

    def test_the_note_is_chosen_with_buttons_from_0_to_10_or_left_empty(self, auth_client, beer):
        modal = self.new_modal(auth_client, beer)
        assert 'name="note" value="" checked' in modal
        assert all(f'name="note" value="{value}"' in modal for value in range(11))

    def test_the_notebook_step_only_exists_for_members_who_have_notebooks(self, auth_client, user, beer):
        assert 'data-title="Carnets"' not in self.new_modal(auth_client, beer)
        f.make_notebook(user, title="Soirée")
        modal = self.new_modal(auth_client, beer)
        assert 'data-title="Carnets"' in modal and "Soirée" in modal and 'sur <span data-stepper-total>5</span>' in modal

    def test_a_page_with_many_modals_reads_the_notebooks_once(self, auth_client, user, django_assert_max_num_queries):
        f.make_notebook(user, title="Soirée")
        for _ in range(8):
            f.make_beer()
        with django_assert_max_num_queries(40):
            assert auth_client.get(reverse("all_beers"), {"tab": "beers"}).status_code == 200

    def test_a_rating_sent_from_the_wizard_is_saved_with_its_context(self, auth_client, user, beer):
        response = auth_client.post(reverse("rate_beer", args=[beer.slug]), {
            "date": timezone.localdate().isoformat(), "note": "8", "comment": "Top", "venue_type": "bar", "company": "friends",
            "serving_format": "bottle", "price": "4.50",
        })
        assert response.status_code == 302
        from app.models import Drinks
        drink = Drinks.objects.get(drinker=user, beer=beer)
        assert (drink.note, drink.venue_type, drink.company, drink.serving_format, str(drink.price)) == (8, "bar", "friends", "bottle", "4.50")

    def test_the_edit_modal_keeps_the_saved_values_and_shows_the_context_summary(self, auth_client, user, beer):
        f.make_drink(user, beer, note=7, comment="Très bonne", venue_type="bar", company="friends", serving_format="can", price="3.20")
        html = auth_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()
        modal = html[html.index('<dialog id="modalEditRating-'):]
        modal = modal[:modal.index("</dialog>")]
        assert 'value="7"' in modal and "Très bonne" in modal and 'name="notebooks"' not in modal
        assert "Canette 33 cl" in modal and "Bar" in modal and "Amis" in modal and "3.20" in modal.replace(",", ".")
        assert 'aria-label="Fermer"' in modal and "Supprimer mon avis" in modal and 'id="form-delete-rating"' in modal

    def test_the_edit_modal_summarises_the_context_or_says_it_is_optional(self, auth_client, user, beer):
        f.make_drink(user, beer, note=5)
        html = auth_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()
        assert "Facultatif : le contexte de cette dégustation" in html

    def test_the_notebook_edit_modal_uses_the_same_template_and_its_own_delete_flow(self, auth_client, user, beer):
        drink = f.make_drink(user, beer, note=6)
        html = auth_client.get(reverse("notebook_all")).content.decode()
        modal = html[html.index(f'<dialog id="modalEditDrink-{drink.slug}"'):]
        modal = modal[:modal.index("</dialog>")]
        assert 'aria-label="Fermer"' in modal and f'id="form-delete-drink-{drink.slug}"' in modal and f"modal_confirm_drink_{drink.slug}" in modal

    def test_every_notebook_is_offered_as_a_choice_chip(self, auth_client, user, beer):
        f.make_notebook(user, title="Soirée")
        html = auth_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()
        assert 'name="notebooks"' in html and "Soirée" in html and "pb-choice" in html

    def test_the_page_marks_javascript_so_the_steps_fall_back_to_one_long_form(self, auth_client):
        html = auth_client.get(reverse("index")).content.decode()
        assert "classList.add('js')" in html and "script/modal_steps.js" in html


class TestNotebookModals:
    """Création et modification d'un carnet : mêmes champs, croix de fermeture, choix des dégustations avec recherche."""

    def modal(self, html, modal_id):
        block = html[html.index(f'<dialog id="{modal_id}"'):]
        return block[:block.index("</dialog>")]

    def test_the_create_modal_keeps_its_form_and_gets_a_close_button(self, auth_client, user):
        f.make_drink(user, f.make_beer(name="Zinc Witbier"), note=8)
        modal = self.modal(auth_client.get(reverse("notebook")).content.decode(), "modal_create_notebook")
        assert f'action="{reverse("create_custom_notebook")}"' in modal and 'name="title"' in modal and 'maxlength="150"' in modal
        assert 'name="description"' in modal and 'name="drinks"' in modal and "Créer le carnet" in modal
        assert 'aria-label="Fermer"' in modal and "Zinc Witbier" in modal and "8/10" in modal

    def test_each_tasting_shows_its_brewery_and_can_be_searched(self, auth_client, user):
        f.make_drink(user, f.make_beer(name="Zinc Witbier", brewery=f.make_brewery(name="Brasserie du Port")))
        modal = self.modal(auth_client.get(reverse("notebook")).content.decode(), "modal_create_notebook")
        assert "Brasserie du Port" in modal and f'data-picker-url="{reverse("load_more_generic", args=["pick_drinks"])}?mode=drinks"' in modal
        assert "data-picker-search" in modal and "data-picker-all" in modal and "data-picker-none" in modal and "data-picker-count" in modal

    def test_a_member_without_tastings_gets_an_explanation_instead_of_an_empty_box(self, auth_client):
        modal = self.modal(auth_client.get(reverse("notebook")).content.decode(), "modal_create_notebook")
        assert "pas encore de dégustation" in modal and "data-picker-search" not in modal

    def test_the_edit_modal_checks_the_tastings_already_in_the_notebook(self, auth_client, user):
        inside, outside = f.make_drink(user, f.make_beer(name="Dedans")), f.make_drink(user, f.make_beer(name="Dehors"))
        notebook = f.make_notebook(user, title="Soirée", description="Une note", drinks=[inside])
        modal = self.modal(auth_client.get(reverse("notebook_detail", args=[notebook.slug])).content.decode(), "modal_edit_notebook")
        # La sélection est donnée au script (picker.js), qui la garde d'une page de résultats à l'autre
        assert f'data-selected="{inside.slug}"' in modal and inside.slug in modal and outside.slug in modal
        assert 'value="Soirée"' in modal and "Une note" in modal and "sur 2" in modal
        assert 'aria-label="Fermer"' in modal and f'action="{reverse("edit_custom_notebook", args=[notebook.slug])}"' in modal

    def test_the_picker_does_not_query_per_tasting(self, auth_client, user, django_assert_max_num_queries):
        for _ in range(15):
            f.make_drink(user, f.make_beer())
        with django_assert_max_num_queries(22):
            assert auth_client.get(reverse("notebook")).status_code == 200

    def test_the_three_dots_menus_share_one_style(self, auth_client, user, beer, other_user):
        pages = [auth_client.get(reverse("beer_detail", args=[beer.slug])), auth_client.get(reverse("public_profile", args=[other_user.username]))]
        assert all("pb-menu" in page.content.decode() and "bg-base-200 rounded-box" not in page.content.decode() for page in pages)

    def test_a_posted_notebook_still_attaches_only_my_own_tastings(self, auth_client, user, other_user):
        mine, foreign = f.make_drink(user), f.make_drink(other_user)
        auth_client.post(reverse("create_custom_notebook"), {"title": "Test", "description": "x", "drinks": [mine.slug, foreign.slug]})
        from app.models import CustomNotebook
        assert list(CustomNotebook.objects.get(user=user).drinks.all()) == [mine]


class TestBeerPageDesign:
    def beer_page(self, client, beer):
        return client.get(reverse("beer_detail", args=[beer.slug]))

    def test_keeps_all_the_data_and_adds_style_and_the_average(self, auth_client, other_user):
        beer = f.make_beer(name="Page Complète", degree=6.5, bitterness=35, style="Stout", description="Notes de café")
        f.make_drink(other_user, beer, note=8)
        html = self.beer_page(auth_client, beer).content.decode()
        for needle in ("Page Complète", "Alc. 6,5 %", "IBU 35", "Stout", "Notes de café", "Ajoutée par", "Note moyenne", "8,0/10", "1 avis"):
            assert needle in html

    def test_voting_hooks_are_untouched(self, auth_client, other_user):
        beer = f.make_beer()
        drink = f.make_drink(other_user, beer, note=7)
        html = self.beer_page(auth_client, beer).content.decode()
        for hook in (f'id="drink-card-{drink.slug}"', f'id="reactions-{drink.slug}"', f'id="likes-count-{drink.slug}"', f'id="dislikes-count-{drink.slug}"',
                     f'id="score-val-{drink.slug}"', 'data-on-click="react"', 'data-on-mousedown="startPress"', 'data-on-touchstart="startPress"',
                     'data-on-click="handleDoubleTap"', f"data-args='[\"{drink.slug}\"", "drink-card", "reaction-menu", f'data-score="{drink.score if hasattr(drink, "score") else 0}"'):
            assert hook in html
        assert "like_dislike_drinks.js" in html

    def test_a_member_can_still_react_to_a_review(self, auth_client, other_user):
        drink = f.make_drink(other_user, f.make_beer(), note=7)
        response = auth_client.post(reverse("toggle_reaction", args=[drink.slug]), data='{"is_like": true}', content_type="application/json")
        assert response.status_code == 200

    def test_own_review_shows_its_context_and_a_score_dot(self, auth_client, user):
        beer = f.make_beer()
        f.make_drink(user, beer, note=9, venue_type="bar", company="friends", serving_format="pint", price="6.50")
        html = self.beer_page(auth_client, beer).content.decode()
        assert "Bar · Amis · Pinte 50 cl · 6,50 €" in html and "border-success text-success" in html
        assert "Votre note" in html and "modalEditRating-" in html

    def test_modals_offer_the_context_fields(self, auth_client, user):
        rated, fresh = f.make_beer(), f.make_beer()
        f.make_drink(user, rated, note=5, venue_type="home", price="3.00")
        edit = self.beer_page(auth_client, rated).content.decode()
        assert 'name="venue_type" value="home" checked' in edit and 'name="price"' in edit and 'value="3.00"' in edit
        new = self.beer_page(auth_client, fresh).content.decode()
        assert 'name="serving_format"' in new and 'name="venue_type"' in new and 'name="company"' in new

    def test_editing_from_the_modal_updates_the_context_and_can_clear_it(self, auth_client, user):
        drink = f.make_drink(user, f.make_beer(), note=5, venue_type="home", company="alone", price="3.00")
        today = timezone.localdate().isoformat()
        auth_client.post(reverse("modify_rate_beer", args=[drink.slug]), {"date": today, "note": 6, "comment": "x", "venue_type": "bar", "company": "", "serving_format": "can", "price": "4.20"})
        drink.refresh_from_db()
        assert (drink.venue_type, drink.company, drink.serving_format, str(drink.price)) == ("bar", "", "can", "4.20")

    def test_wishlist_and_report_features_remain(self, auth_client, other_user):
        beer = f.make_beer(added_by=other_user)
        html = self.beer_page(auth_client, beer).content.decode()
        assert 'data-on-click="toggleWishlist"' in html and "modal_report_beer" in html and "modalRate-" in html

    def test_unverified_own_beer_can_still_be_edited_or_removed(self, auth_client, user):
        beer = f.make_beer(added_by=user)
        html = self.beer_page(auth_client, beer).content.decode()
        assert reverse("edit_beer", args=[beer.slug]) in html and "modal_confirm_beer" in html

    def test_blocked_members_reviews_stay_hidden_and_average_ignores_them(self, auth_client, user, other_user):
        beer = f.make_beer()
        f.make_drink(other_user, beer, note=2)
        f.block(user, other_user)
        response = self.beer_page(auth_client, beer)
        assert response.context["rating_count"] == 0 and "Note moyenne" not in response.content.decode()

    def test_query_count_is_bounded(self, auth_client, django_assert_max_num_queries):
        beer = f.make_beer()
        for _ in range(8):
            f.make_drink(f.make_user(), beer, note=7)
        with django_assert_max_num_queries(40):
            assert self.beer_page(auth_client, beer).status_code == 200


class TestPlacePagesDesign:
    def test_brewery_page_keeps_every_data_and_feature(self, auth_client, user):
        brewery = f.make_brewery(name="Brasserie Test", address="1 rue du Houblon, Lille", website="https://example.org", phone="0102030405", email="b@example.org",
                                 description="Une brasserie de test")
        beer = f.make_beer(name="Blonde Maison", brewery=brewery, style="Blonde", degree=5, bitterness=20)
        html = auth_client.get(reverse("brewery_detail", args=[brewery.slug])).content.decode()
        for needle in ("Brasserie Test", "1 rue du Houblon, Lille", "Une brasserie de test", "https://example.org", "tel:0102030405", "mailto:b@example.org",
                       "Bières proposées (1)", "Blonde Maison", "Blonde", "Alc. 5", "IBU 20", reverse("beer_detail", args=[beer.slug]), "modalRate-", 'data-on-click="toggleWishlist"'):
            assert needle in html
        assert "modal_report_place" in html and "pb-title" in html and "text-justify" not in html

    def test_bar_page_keeps_its_data_and_contact_links(self, auth_client):
        bar = f.make_bar(name="Bar Test", address="2 rue du Bar, Lyon", instagram="https://instagram.com/bar", description="Un bar")
        html = auth_client.get(reverse("bar_detail", args=[bar.slug])).content.decode()
        for needle in ("Bar Test", "2 rue du Bar, Lyon", "Un bar", "https://instagram.com/bar", "modal_report_place"):
            assert needle in html

    def test_manager_still_gets_edit_collaborators_and_add_beer(self, client):
        pro = f.make_user(groups=["Brasseur"])
        brewery = f.make_brewery(name="Ma Brasserie", managers=[pro])
        client.force_login(pro)
        html = client.get(reverse("brewery_detail", args=[brewery.slug])).content.decode()
        assert reverse("edit_brewery", args=[brewery.slug]) in html and "modal_manage_collabs" in html
        assert reverse("add_beer") + "?brewery=" in html
        assert "modal_report_place" not in html

    def test_visitor_can_still_claim_or_report(self, auth_client):
        bar = f.make_bar(name="Bar Libre")
        html = auth_client.get(reverse("bar_detail", args=[bar.slug])).content.decode()
        assert "modal_report_place" in html and reverse("claim_bar", args=[bar.slug]) in html

    def test_brewery_beer_cards_are_bounded_in_queries(self, auth_client, django_assert_max_num_queries):
        brewery = f.make_brewery()
        for _ in range(8):
            f.make_beer(brewery=brewery)
        with django_assert_max_num_queries(40):
            assert auth_client.get(reverse("brewery_detail", args=[brewery.slug])).status_code == 200


class TestMapDesign:
    def page(self, client):
        return client.get(reverse("map")).content.decode()

    def test_every_existing_hook_of_the_map_page_is_still_there(self, auth_client):
        html = self.page(auth_client)
        for hook in ('id="map"', 'id="map-search-input"', 'id="map-search-results"', 'id="geoloc-btn"', 'id="move-overlay"', 'data-on-click="searchLocation"', 'data-on-click="cancelMoveMode"',
                     'data-on-click="finishMoveMode"', 'id="modal_add_spot"', 'id="modal_confirm_spot"', 'id="modal_place"', 'id="form-delete-spot"', 'id="spots-data-container"',
                     'id="places-data-container"', 'data-on-click="startMoveMode"', 'data-on-click="updateToCurrentLocation"', 'id="spot-lat"', 'id="friends-section"'):
            assert hook in html

    def test_place_names_with_apostrophes_are_not_garbled(self, auth_client):
        f.make_bar(name="L'Atelier du Houblon", address="1 rue du Port, Lille")
        html = self.page(auth_client)
        assert "\\u0027" not in html and "L&#x27;Atelier du Houblon" in html

    def test_spot_titles_with_apostrophes_are_not_garbled(self, auth_client, user):
        f.make_spot(user, title="Chez l'ami", latitude=48.85, longitude=2.35)
        html = self.page(auth_client)
        assert "\\u0027" not in html and "Chez l&#x27;ami" in html

    def test_the_place_mini_map_marks_the_kind_of_place(self, auth_client):
        bar = f.make_bar(name="Bar Carte", address="2 rue du Bar, Lyon")
        html = auth_client.get(reverse("bar_detail", args=[bar.slug])).content.decode()
        assert 'data-kind="bar"' in html and html.index("script/pins.js") < html.index("script/mini_map.js")


class TestDropdownsShareOneStyle:
    """Toutes les listes déroulantes du site n'ont qu'une flèche : aucune ne force la flèche du navigateur et le style commun la fournit."""

    def test_no_template_forces_the_native_arrow_back(self):
        from pathlib import Path
        offenders = [str(path) for path in Path("app/templates").rglob("*.html")
                     if "admin" not in path.parts and ("appearance-auto" in path.read_text() or "-webkit-appearance: auto" in path.read_text())]
        assert offenders == []

    def test_the_stylesheet_gives_every_select_a_single_custom_arrow(self):
        from pathlib import Path
        css = Path("app/static/style/ui.css").read_text()
        assert "select:not([multiple]):not([size])" in css and "appearance: none" in css and ".pb-select" in css

    def test_the_report_and_top_beer_selects_use_the_shared_class(self, auth_client, user, beer):
        html = auth_client.get(reverse("beer_detail", args=[beer.slug])).content.decode()
        assert 'class="pb-select"' in html and "appearance-auto" not in html
