"""Styles de bière : familles en table, styles liés à la bière (dans l'ordre, un principal), styles « à valider », suggestions et administration."""
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from app.admin.pending import pending_unofficial_style_count
from app.domain import style_catalog, style_structure, styles as style_rules
from app.forms import BeerForm
from app.models import Beer, BeerStyle, Style, StyleFamily
from app.services.catalog import style_registry
from app.services.catalog.styles import catalog_styles
from tests import factories as f

pytestmark = pytest.mark.django_db


def names(beer):
    return list(beer.beer_styles.order_by("position").values_list("style__name", flat=True))


class TestCatalogData:
    def test_every_name_and_alias_designates_one_style_only(self):
        seen = {}
        for name, _family, aliases in style_catalog.STYLE_CATALOG:
            for written in (name, *aliases):
                key = style_rules.style_key(written)
                assert seen.setdefault(key, name) == name, f"« {written} » désigne {seen[key]} et {name}"

    def test_every_style_has_a_known_family_and_the_catalog_is_wide(self):
        assert {family for _n, family, _a in style_catalog.STYLE_CATALOG} <= set(style_catalog.FAMILIES)
        assert len(style_catalog.STYLE_CATALOG) >= 90 and len({n for n, _f, _a in style_catalog.STYLE_CATALOG}) == len(style_catalog.STYLE_CATALOG)

    def test_the_database_is_seeded_with_the_whole_catalog_in_ordered_families(self):
        assert Style.objects.filter(is_official=True).count() >= len(style_catalog.STYLE_CATALOG)
        assert not Style.objects.filter(family__isnull=True, is_official=True).exists()
        assert list(StyleFamily.objects.values_list("name", flat=True))[:len(style_catalog.FAMILIES)] == list(style_catalog.FAMILIES)

    @pytest.mark.parametrize("written, official", [("hazy ipa", "NEIPA"), ("Gueuze", "Gueuze"), ("0.0", "Sans alcool"), ("Oktoberfest", "Märzen"),
                                                    ("tripel", "Triple"), ("bière au miel", "Honey Beer")])
    def test_common_spellings_resolve_to_the_official_style(self, written, official):
        assert style_registry.canonicalize(written) == official and style_registry.recognized(official)


class TestStructure:
    def test_styles_are_linked_in_order_and_the_first_recognised_one_is_primary(self):
        beer = f.make_beer(style="Inconnu total, stout, ipa")
        beer.refresh_from_db()
        assert names(beer) == ["Inconnu total", "Stout", "IPA"]
        assert (beer.primary_style.name, beer.style_family_name) == ("Stout", "Brune, porter et stout")
        assert beer.style == "Inconnu total, Stout, IPA"

    def test_a_beer_without_style_has_no_link(self):
        beer = f.make_beer(style=None)
        assert not beer.beer_styles.exists() and beer.primary_style is None and beer.style_family_name == ""

    def test_changing_the_style_replaces_the_links(self):
        beer = f.make_beer(style="IPA, Stout")
        beer.style = "Gose"
        beer.save()
        assert names(beer) == ["Gose"] and Beer.objects.get(pk=beer.pk).primary_style.name == "Gose"
        beer.style = ""
        beer.save()
        assert names(beer) == [] and Beer.objects.get(pk=beer.pk).primary_style is None

    def test_saving_without_touching_the_style_does_not_rebuild(self, django_assert_num_queries):
        beer = Beer.objects.get(pk=f.make_beer(style="IPA").pk)
        beer.degree = 6
        with django_assert_num_queries(1):  # le seul UPDATE de la bière
            beer.save(update_fields=["degree"])

    def test_a_style_is_never_linked_twice_to_a_beer(self):
        beer = f.make_beer(style="IPA, india pale ale, ipa")
        assert names(beer) == ["IPA"]
        with pytest.raises(IntegrityError), transaction.atomic():
            BeerStyle.objects.create(beer=beer, style=Style.objects.get(name="IPA"), position=5)

    def test_at_most_three_styles_are_kept(self):
        beer = f.make_beer(style="IPA, Stout, Gose, Blonde")
        assert names(beer) == ["IPA", "Stout", "Gose"] and beer.style == "IPA, Stout, Gose"

    def test_the_label_never_exceeds_the_column(self):
        registry = style_structure.Registry([])
        assert len(", ".join(style_structure.labels("a" * 60 + ", " + "b" * 60, registry))) <= style_structure.MAX_LABEL_LENGTH

    def test_the_form_refuses_more_than_three_styles(self, user):
        form = BeerForm({"name": "X", "degree": "5", "style": "IPA, Stout, Gose, Blonde"}, user=user)
        assert not form.is_valid() and "3 styles au plus" in form.errors["style"][0]

    def test_the_form_refuses_markup_in_a_style(self, user):
        assert "style" in BeerForm({"name": "X", "degree": "5", "style": "<b>IPA</b>"}, user=user).errors

    def test_a_beer_family_is_read_through_its_primary_style(self):
        beer = f.make_beer(style="Stout")
        StyleFamily.objects.filter(name="Brune, porter et stout").update(name="Noires")
        assert Beer.objects.select_related("primary_style__family").get(pk=beer.pk).style_family_name == "Noires"  # un renommage vaut partout


class TestPendingStyles:
    def test_an_unknown_style_is_created_once_for_all_beers(self):
        first, second = f.make_beer(style="Zythos"), f.make_beer(style="zythos")
        assert Style.objects.filter(name="Zythos", is_official=False).count() == 1
        assert first.primary_style_id == second.primary_style_id and pending_unofficial_style_count() == 1

    def test_the_team_can_validate_a_style_by_giving_it_a_family(self):
        beer = f.make_beer(style="Zythos")
        pending = Style.objects.get(name="Zythos")
        pending.family = StyleFamily.objects.get(name="IPA")
        pending.is_official = True
        pending.save()
        assert style_registry.recognized("Zythos") and style_registry.family_of("Zythos") == "IPA"
        style_registry.rebuild_all()
        assert Beer.objects.get(pk=beer.pk).style_family_name == "IPA"

    def test_an_official_style_needs_a_family(self):
        with pytest.raises(ValidationError):
            Style(name="Sans famille", is_official=True).full_clean()
        with pytest.raises(IntegrityError), transaction.atomic():
            Style.objects.create(name="Sans famille", is_official=True)

    def test_merging_into_an_official_style_removes_the_useless_one(self):
        beer = f.make_beer(style="Geuze lambic ancienne")
        Style.objects.filter(name="Gueuze").update(aliases="Geuze\nGeuze lambic ancienne")
        style_registry.rebuild_all()
        assert Beer.objects.get(pk=beer.pk).style == "Gueuze" and not Style.objects.filter(name="Geuze lambic ancienne").exists()

    def test_rebuild_all_is_idempotent_and_repairs_bulk_writes(self):
        beers = Beer.objects.bulk_create([Beer(name="Brute", brewery=f.make_brewery(), degree=5, style="hazy ipa")])
        assert style_registry.rebuild_all() >= 1 and style_registry.rebuild_all() == 0
        assert names(Beer.objects.get(pk=beers[0].pk)) == ["NEIPA"]


class TestSuggestions:
    def test_a_name_starting_with_the_term_comes_before_an_alias_and_a_middle_match(self):
        found = [item["name"] for item in style_registry.suggest("stou")]
        assert found[0] == "Stout" and "Milk Stout" in found[1:] and len(style_registry.suggest("i")) == style_registry.SUGGESTIONS
        assert [item["name"] for item in style_registry.suggest("ipa")][0] == "IPA"

    def test_an_alias_leads_to_its_official_style_with_the_family(self):
        assert {"name": "Gueuze", "family": "Lambic et fermentation spontanée"} in style_registry.suggest("geuze")

    def test_accents_and_case_are_ignored(self):
        assert any(item["name"] == "Märzen" for item in style_registry.suggest("MARZ"))

    @pytest.mark.parametrize("term", ["", "   ", "zzzzzz"])
    def test_nothing_for_an_empty_or_unknown_term(self, term):
        assert style_registry.suggest(term) == []

    def test_unofficial_styles_are_not_suggested(self):
        f.make_beer(style="Zythos exotique")
        assert style_registry.suggest("zythos") == []

    def test_the_endpoint_needs_a_login_and_returns_name_and_family(self, auth_client, client):
        url = reverse("search_style")
        assert auth_client.get(url, {"term": "stou"}).json()[0] == {"name": "Stout", "family": "Brune, porter et stout"}
        assert client.get(url, {"term": "stou"}).status_code == 302

    def test_suggesting_costs_no_query_once_the_registry_is_cached(self, django_assert_num_queries):
        style_registry.suggest("ipa")  # réchauffe le cache du référentiel
        with django_assert_num_queries(0):
            style_registry.suggest("ipa")


class TestCatalogStyles:
    def test_filters_list_the_styles_in_use_by_the_live_catalog(self):
        f.make_beer(style="Gose")
        removed = f.make_beer(style="Eisbock")
        Beer.objects.filter(pk=removed.pk).update(is_deleted=True)
        styles = catalog_styles()
        assert "Gose" in styles and "Eisbock" not in styles and styles == sorted(styles)

    def test_the_list_follows_a_new_beer_at_once(self):
        assert "Sahti" not in catalog_styles()
        f.make_beer(style="Sahti")
        assert "Sahti" in catalog_styles()


class TestAdmin:
    def test_the_families_are_editable_with_their_style_count(self, client_for, superuser):
        response = client_for(superuser).get(reverse("admin:app_stylefamily_changelist"))
        assert response.status_code == 200 and "IPA" in response.content.decode()

    def test_the_styles_to_validate_have_their_own_queue(self, client_for, superuser):
        f.make_beer(style="Zythos")
        response = client_for(superuser).get(reverse("admin:app_style_changelist"), {"is_official__exact": "0"})
        assert response.context["pending_count"] == 1 and [s.name for s in response.context["cl"].result_list] == ["Zythos"]

    def test_the_sidebar_links_to_the_queue(self, settings):
        items = {item["title"]: item for group in settings.UNFOLD["SIDEBAR"]["navigation"] for item in group["items"]}
        assert items["Styles à valider"]["badge"] == "app.admin.pending.pending_unofficial_style_count"

    def test_approving_needs_a_family(self, client_for, superuser):
        f.make_beer(style="Zythos")
        f.make_beer(style="Exotic")
        with_family = Style.objects.get(name="Zythos")
        with_family.family = StyleFamily.objects.get(name="Sans alcool et légère")
        with_family.save()
        client = client_for(superuser)
        response = client.post(reverse("admin:app_style_changelist"), {
            "action": "approve", "_selected_action": list(Style.objects.filter(is_official=False).values_list("pk", flat=True)),
        }, follow=True)
        assert response.status_code == 200
        assert Style.objects.get(name="Zythos").is_official and not Style.objects.get(name="Exotic").is_official
        assert any("n'ont pas été validés" in str(message) for message in response.context["messages"])

    def test_the_rebuild_action_reports_the_count(self, client_for, superuser):
        beer = f.make_beer(style="Stout")
        Beer.objects.filter(pk=beer.pk).update(style="stout")
        response = client_for(superuser).post(reverse("admin:app_style_changelist"), {
            "action": "renormalize_beers", "_selected_action": [Style.objects.first().pk]}, follow=True)
        assert "1 bière(s) mise(s) à jour" in response.content.decode()

    def test_a_style_in_use_cannot_be_deleted(self, client_for, superuser):
        beer = f.make_beer(style="Stout")
        stout = beer.styles.get()
        response = client_for(superuser).post(reverse("admin:app_style_delete", args=[stout.pk]), {"post": "yes"}, follow=True)
        assert Style.objects.filter(pk=stout.pk).exists() and response.status_code == 200
