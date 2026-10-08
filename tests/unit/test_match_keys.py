"""Clés de comparaison des noms : ce qui rend deux noms « identiques » ou « proches », et ce qui les garde distincts."""
import pytest

from app.services import match_keys as keys

BEER, BREWERY = keys.BEER, keys.BREWERY


def same_brewery(a, b):
    return keys.strict_key(a, BREWERY) == keys.strict_key(b, BREWERY)


def brewery_similarity(a, b):
    return keys.similarity(keys.loose_tokens(a, BREWERY), keys.loose_tokens(b, BREWERY))


def beer_similarity(a, b):
    return keys.similarity(keys.loose_tokens(a), keys.loose_tokens(b))


class TestTokens:
    @pytest.mark.parametrize("raw, expected", [
        ("Bière de Noël", ["biere", "de", "noel"]), ("I.P.A", ["ipa"]), ("i p a", ["ipa"]), ("L'Estuaire", ["l", "estuaire"]),
        ("  Double   IPA ", ["double", "ipa"]), ("", []), (None, []), ("!!!", []), ("Œuvre", ["oeuvre"]),
    ])
    def test_normalised_words(self, raw, expected):
        assert keys.tokens(raw, BREWERY) == expected

    @pytest.mark.parametrize("raw, expected", [
        ("Punk IPA 33cl", ["punk", "ipa"]), ("Punk IPA 5,6%", ["punk", "ipa"]), ("Punk IPA 5.6 %", ["punk", "ipa"]), ("Punk IPA 0,75 L", ["punk", "ipa"]),
        ("Kronenbourg 1664", ["kronenbourg", "1664"]), ("Houblon 2", ["houblon", "2"]), ("Duvel 8", ["duvel", "8"]),
    ])
    def test_a_beer_loses_its_quantities_but_keeps_its_numbers(self, raw, expected):
        assert keys.tokens(raw, BEER) == expected

    def test_a_brewery_name_keeps_its_numbers_and_units(self):
        assert keys.tokens("Brasserie 33", BREWERY) == ["brasserie", "33"]

    def test_input_is_bounded(self):
        assert len(keys.strict_key("a" * 5000)) <= keys.KEY_LENGTH
        assert len(keys.tokens("mot " * 5000)) <= keys.MAX_NAME_LENGTH // 3

    def test_keys_are_deterministic_and_sorted(self):
        assert keys.strict_key("Punk IPA") == keys.strict_key("IPA Punk") == "ipa punk"


class TestBreweryNames:
    @pytest.mark.parametrize("other", ["Brasserie du Coin", "brasserie du coin", "BRASSERIE DU COIN", "La Brasserie Du Coin SAS", "Brasserie du Coin !", "Brasserie  du-Coin", "Coin Brasserie", "Brasserie Coin"])
    def test_identical_after_removing_what_does_not_identify(self, other):
        assert same_brewery("Brasserie du Coin", other)

    @pytest.mark.parametrize("other", ["Microbrasserie du Coin", "Du Coin", "Coin Brewery", "Coin Brewing Co", "Atelier du Coin", "Les Brasseurs du Coin"])
    def test_generic_words_make_it_close_but_not_identical(self, other):
        assert not same_brewery("Brasserie du Coin", other)
        assert brewery_similarity("Brasserie du Coin", other) == 1.0

    def test_typos_in_a_long_name_are_close(self):
        assert brewery_similarity("Brasserie Parisienne", "Brasserie Parisiene") >= keys.PROBABLE_SIMILARITY

    @pytest.mark.parametrize("a, b", [
        ("Brasserie Parisienne du Canal", "Brasserie Parisienne du Port"), ("Brasserie du Nord", "Brasserie du Sud"),
        ("Brasserie des Alpes", "Brasserie des Flandres"), ("Brasserie 1", "Brasserie 2"),
    ])
    def test_different_identifying_words_stay_distinct(self, a, b):
        assert brewery_similarity(a, b) < keys.PROBABLE_SIMILARITY

    def test_a_name_made_only_of_generic_words_keeps_them(self):
        assert keys.loose_key("Brasserie", BREWERY) == "brasserie" and keys.strict_key("La Brasserie", BREWERY) == "brasserie"


class TestBeerNames:
    @pytest.mark.parametrize("other", ["Punk IPA", "PUNK IPA", "Punk I.P.A.", "Punk IPA 33cl", "Punk IPA 5,6%", "IPA Punk", "Bière Punk IPA", "punk-ipa"])
    def test_identical_beers(self, other):
        assert keys.strict_key("Punk IPA") == keys.strict_key(other)

    @pytest.mark.parametrize("a, b", [("Leffe Blond", "Leffe Blonde"), ("Triple Karmeliet", "Triple Karmeliett"), ("Punk IPAA", "Punk IPA")])
    def test_typos_are_close(self, a, b):
        assert beer_similarity(a, b) >= keys.PROBABLE_SIMILARITY

    @pytest.mark.parametrize("a, b", [
        ("Houblon 1", "Houblon 2"), ("Stout", "Imperial Stout"), ("Blonde", "Blanche"), ("Brune", "Brume"), ("IPA", "IPL"),
        ("Pils", "Pale Ale"), ("Triple", "Double"), ("Duvel", "Duvel Tripel Hop"), ("1664", "1664 Blanc"),
    ])
    def test_different_beers_stay_distinct(self, a, b):
        assert beer_similarity(a, b) < keys.PROBABLE_SIMILARITY

    def test_numbers_decide(self):
        assert keys.similarity(["houblon", "1"], ["houblon", "2"]) == 0.0
        assert keys.similarity(["houblon", "1"], ["houblon", "1"]) == 1.0

    def test_short_names_only_match_when_equal(self):
        assert keys.similarity(["brune"], ["brume"]) == 0.0 and keys.similarity(["brune"], ["brune"]) == 1.0


class TestWithout:
    def test_the_brewery_name_copied_into_the_beer_name_is_ignored(self):
        assert keys.without(["brewdog", "ipa", "punk"], ["brewdog"]) == ["ipa", "punk"]

    def test_nothing_is_removed_if_nothing_would_remain(self):
        assert keys.without(["brewdog"], ["brewdog"]) == ["brewdog"]
