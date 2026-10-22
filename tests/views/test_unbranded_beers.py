"""Bières sans brasserie (le membre ne la connaissait pas) : affichage partout, file de travail du staff, recherche et doublons."""
import pytest
from django.urls import reverse

from app.admin.pending import pending_unbranded_beer_count
from app.models import Beer, BeerDraft
from app.services.catalog import catalog_matching as cm
from tests import factories as f

pytestmark = pytest.mark.django_db

UNKNOWN = Beer.UNKNOWN_BREWERY


@pytest.fixture
def pinte(user):
    return f.make_beer(name="Pinte du comptoir", unbranded=True, degree=5, added_by=user)


class TestDisplay:
    def test_the_beer_page_says_the_brewery_is_unknown_without_a_link(self, auth_client, pinte):
        html = auth_client.get(reverse("beer_detail", args=[pinte.slug])).content.decode()
        assert UNKNOWN in html and "Pinte du comptoir" in html

    def test_the_catalog_search_lists_it(self, auth_client, pinte):
        html = auth_client.get(reverse("api_search"), {"q": "pinte"}).content.decode()
        assert "Pinte du comptoir" in html and UNKNOWN in html

    def test_the_wishlist_and_tastings_show_it(self, auth_client, user, pinte):
        user.wishlist_beers.add(pinte)
        f.make_drink(user, pinte)
        for tab in ("to-taste", "tasted"):
            response = auth_client.get(reverse("notebook"), {"tab": tab})
            assert response.status_code == 200
        assert UNKNOWN in auth_client.get(reverse("notebook_wishlist_fragment")).content.decode()
        assert UNKNOWN in auth_client.get(reverse("account")).content.decode()

    def test_the_autocompletes_name_it(self, auth_client, pinte):
        found = auth_client.get(reverse("search_beer"), {"term": "pinte"}).json()
        assert found == [{"name": "Pinte du comptoir", "slug": pinte.slug, "brewery": UNKNOWN}]

    def test_it_can_be_rated_and_edited(self, auth_client, pinte):
        assert auth_client.post(reverse("rate_beer", args=[pinte.slug]), {"date": "2026-01-15", "comment": "Bonne", "note": 7}).status_code == 302
        edit = auth_client.get(reverse("edit_beer", args=[pinte.slug]))
        assert edit.status_code == 200 and edit.context["form"]["brewery_name"].value() in ("", None)

    def test_editing_without_a_brewery_keeps_it_unknown(self, auth_client, pinte):
        auth_client.post(reverse("edit_beer", args=[pinte.slug]), {"name": "Pinte du comptoir", "degree": "5", "brewery_name": ""})
        pinte.refresh_from_db()
        assert pinte.brewery is None

    def test_the_semantic_text_does_not_invent_a_brewery(self, pinte):
        assert "brasserie" not in pinte.embedding_text and "non renseigné" in pinte.embedding_text


class TestMatching:
    def test_same_name_and_degree_without_brewery_is_the_same_beer(self, pinte):
        report = cm.find_beer("pinte du comptoir", "", degree=pinte.degree)
        assert report.level == cm.Level.SAME and report.same.obj == pinte

    def test_another_degree_is_another_beer(self, pinte):
        assert cm.find_beer("Pinte du comptoir", "", degree=6).level == cm.Level.NONE

    def test_the_name_of_a_branded_beer_is_only_a_notice(self):
        branded = f.make_beer(name="Houblon Royal")
        report = cm.find_beer("Houblon Royal", "", degree=branded.degree)
        assert report.level == cm.Level.NONE and [c.obj for c in report.elsewhere] == [branded]

    def test_the_admin_duplicate_screen_ignores_unbranded_beers(self, pinte):
        f.make_beer(name="Pinte du comptoir", unbranded=True, degree=6)
        assert cm.duplicate_beers() == []

    def test_the_live_check_uses_the_degree(self, auth_client, pinte):
        check = reverse("check_catalog")
        same = auth_client.get(check, {"name": "Pinte du comptoir", "degree": "5"}).json()["html"]
        other = auth_client.get(check, {"name": "Pinte du comptoir", "degree": "6,5"}).json()["html"]
        junk = auth_client.get(check, {"name": "Pinte du comptoir", "degree": "beaucoup"}).json()["html"]
        assert "déjà au catalogue" in same and "déjà au catalogue" not in other and "déjà au catalogue" not in junk


class TestStaffQueue:
    def test_only_active_unbranded_beers_are_counted(self, pinte):
        f.make_beer(name="Avec brasserie")
        f.make_beer(name="Retirée", unbranded=True, degree=7, is_deleted=True)
        assert pending_unbranded_beer_count() == 1 and Beer.objects.unbranded().get() == pinte

    def test_the_changelist_filters_on_the_brewery_and_shows_the_count(self, client_for, superuser, pinte):
        branded = f.make_beer(name="Rattachée")
        client = client_for(superuser)
        response = client.get(reverse("admin:app_beer_changelist"), {"brewery_known": "no"})
        assert response.status_code == 200 and response.context["pending_count"] == 1
        assert [b.pk for b in response.context["cl"].result_list] == [pinte.pk]
        known = client.get(reverse("admin:app_beer_changelist"), {"brewery_known": "yes"})
        assert [b.pk for b in known.context["cl"].result_list] == [branded.pk]

    def test_the_staff_attaches_a_brewery_from_the_beer_page(self, client_for, superuser, pinte):
        brewery = f.make_brewery(name="Brasserie Retrouvée")
        client = client_for(superuser)
        url = reverse("admin:app_beer_change", args=[pinte.pk])
        assert client.get(url).status_code == 200
        response = client.post(url, {"name": pinte.name, "degree": "5.0", "brewery": brewery.pk, "is_verified": "on", "description": "", "style": ""})
        assert response.status_code == 302
        pinte.refresh_from_db()
        assert pinte.brewery == brewery and pinte.is_verified and not Beer.objects.unbranded().exists()

    def test_the_brewery_is_searched_by_name_or_city_in_the_picker(self, client_for, superuser):
        f.make_brewery(name="Brasserie Alpha", city="Lyon")
        response = client_for(superuser).get(reverse("admin:autocomplete"), {"term": "Lyon", "app_label": "app", "model_name": "beer", "field_name": "brewery"})
        assert response.status_code == 200 and [r["text"] for r in response.json()["results"]] == ["Brasserie Alpha (Lyon)"]

    def test_the_sidebar_links_to_the_queue(self, settings):
        items = {item["title"]: item for group in settings.UNFOLD["SIDEBAR"]["navigation"] for item in group["items"]}
        queue = items["Bières à compléter"]
        assert queue["badge"] == "app.admin.pending.pending_unbranded_beer_count" and str(queue["link"]).endswith("?brewery_known=no")


class TestUnbrandedDraft:
    def test_a_draft_without_a_brewery_resumes(self, auth_client, user):
        BeerDraft.objects.create(user=user, data={"beer-name": "Pinte", "beer-degree": "5"}, current_step=2)
        response = auth_client.get(reverse("add_beer"))
        assert response.context["start_step"] == 2 and "Pinte" in response.content.decode()


class TestBreweryLabel:
    @pytest.mark.parametrize("fields, label", [
        ({}, "Brasserie du Coin"),
        ({"postal_code": "44000", "city": "Nantes"}, "Brasserie du Coin (44000 Nantes)"),
        ({"city": "Lyon"}, "Brasserie du Coin (Lyon)"),
        ({"postal_code": "69001"}, "Brasserie du Coin (69001)"),
    ])
    def test_the_place_tells_two_homonyms_apart_in_the_admin(self, fields, label):
        assert str(f.make_brewery(name="Brasserie du Coin", **fields)) == label


class TestNoDescription:
    """Une bière sans description (celles ajoutées par un membre) n'affiche ni « None » ni paragraphe vide."""

    def test_no_page_prints_none_for_a_missing_description(self, auth_client, user):
        beer = f.make_beer(name="Sans mots", description=None, added_by=user, brewery=f.make_brewery(name="Brasserie Muette"))
        pages = [
            auth_client.get(reverse("beer_detail", args=[beer.slug])),
            auth_client.get(reverse("api_search"), {"q": "sans mots"}),
            auth_client.get(reverse("brewery_detail", args=[beer.brewery.slug])),
        ]
        for response in pages:
            html = response.content.decode()
            assert "Sans mots" in html and ">None<" not in html and "None</p>" not in html
