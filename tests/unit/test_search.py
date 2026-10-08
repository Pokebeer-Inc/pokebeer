"""Moteur de recherche : accents, plusieurs mots, fautes de frappe, pertinence, caractères spéciaux."""
import pytest

from app.models import Bar, Beer, BeerUser, Brewery
from app.services import search
from tests import factories as f

pytestmark = pytest.mark.django_db


def beer_names(query, **kwargs):
    return [b.name for b in search.beers(Beer.objects.filter(is_deleted=False), query).order_by(search.RANK_FIELD, "name")]


class TestNormalisation:
    @pytest.mark.parametrize("raw, expected", [
        ("Bière de Noël", "biere de noel"), ("ŒUVRE", "oeuvre"), ("Straße", "strasse"), ("  ", ""), (None, ""),
    ])
    def test_lowercase_without_accents(self, raw, expected):
        assert search.normalize(raw) == expected

    def test_terms_are_bounded_and_deduplicated(self):
        assert search.terms("a A b " + "x " * 50) == ["a", "b", "x"]
        assert len(search.terms(" ".join(f"mot{i}" for i in range(50)))) == search.MAX_TERMS
        assert len(search.terms("é" * 10_000)[0]) == search.MAX_QUERY_LENGTH


class TestBeers:
    def test_no_query_keeps_everything(self):
        f.make_beer(name="Une"), f.make_beer(name="Deux")
        assert sorted(beer_names("")) == ["Deux", "Une"]

    def test_accents_and_case_are_ignored_both_ways(self):
        f.make_beer(name="Bière de Noël")
        assert beer_names("BIERE DE NOEL") == ["Bière de Noël"]
        f.make_beer(name="Brune")
        assert beer_names("bière") == ["Bière de Noël"]

    def test_every_word_must_match_somewhere_name_brewery_or_style(self):
        brewery = f.make_brewery(name="Brasserie du Coin")
        f.make_beer(name="Soleil", brewery=brewery, style="IPA")
        f.make_beer(name="Soleil Noir", style="Stout")
        assert beer_names("soleil ipa coin") == ["Soleil"]
        assert beer_names("soleil ipa lune") == []

    def test_small_typos_are_tolerated_for_longer_words(self):
        f.make_beer(name="Brasserie Blonde")
        f.make_beer(name="Triple Karmeliet")
        assert beer_names("karmelit") == ["Triple Karmeliet"]
        assert beer_names("blonde") == ["Brasserie Blonde"]
        assert beer_names("karmeliet") == ["Triple Karmeliet"]
        assert beer_names("karmeliett") == ["Triple Karmeliet"]

    def test_relevance_exact_then_prefix_then_word_then_other(self):
        f.make_beer(name="Super Stout Imperial")
        f.make_beer(name="Stout")
        f.make_beer(name="Stoutissime")
        f.make_beer(name="Imperial", style="Stout")
        assert beer_names("stout") == ["Stout", "Stoutissime", "Super Stout Imperial", "Imperial"]

    @pytest.mark.parametrize("hostile", ["100%", "_", "\\", "'; DROP TABLE app_beer; --", "%%%", "a" * 500])
    def test_special_characters_are_searched_literally(self, hostile):
        f.make_beer(name="Bière 100%")
        f.make_beer(name="Bière 100 pur")
        found = beer_names(hostile)
        assert found == (["Bière 100%"] if hostile == "100%" else [])
        assert Beer.objects.count() == 2

    def test_digits_are_not_fuzzy(self):
        f.make_beer(name="Bière 1000")
        assert beer_names("1001") == []


class TestOtherKinds:
    def test_breweries_match_name_or_address(self):
        f.make_brewery(name="Mousse d'Or", address="12 rue des Brasseurs, Lyon")
        f.make_brewery(name="Autre", address="Paris")
        names = lambda q: [b.name for b in search.breweries(Brewery.objects.all(), q)]
        assert names("mousse") == ["Mousse d'Or"] and names("lyon") == ["Mousse d'Or"] and names("MOUSSE lyon") == ["Mousse d'Or"]

    def test_bars_and_members(self):
        f.make_bar(name="Le Bar à Bières")
        f.make_user(username="alice_beer")
        assert [b.name for b in search.bars(Bar.objects.all(), "bar a bieres")] == ["Le Bar à Bières"]
        assert [u.username for u in search.members(BeerUser.objects.all(), "ALICE")] == ["alice_beer"]
