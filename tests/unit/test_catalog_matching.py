"""Détection des doublons du catalogue : verdicts, confirmations signées, ajout, détection des paires existantes."""
import pytest
from django.core import signing

from app.models import Beer, Brewery
from app.services import catalog_matching as cm
from tests import factories as f

pytestmark = pytest.mark.django_db

SAME, PROBABLE, ELSEWHERE, NONE = cm.Level.SAME, cm.Level.PROBABLE, cm.Level.ELSEWHERE, cm.Level.NONE


def verdicts(report):
    return sorted((c.obj.name, c.level.name) for c in report.candidates)


@pytest.fixture
def coin():
    return f.make_brewery(name="Brasserie du Coin")


class TestFindBrewery:
    @pytest.mark.parametrize("typed", ["Brasserie du Coin", "brasserie DU coin", "La Brasserie Du Coin SAS", "Brasserie Coin"])
    def test_an_identical_brewery_is_recognised(self, coin, typed):
        assert verdicts(cm.find_brewery(typed)) == [("Brasserie du Coin", "SAME")] and cm.find_brewery(typed).level == SAME

    @pytest.mark.parametrize("typed", ["Microbrasserie du Coin", "Du Coin", "Coin Brewing Company", "Les Brasseurs du Coin"])
    def test_a_brewery_with_other_generic_words_is_probably_the_same(self, coin, typed):
        report = cm.find_brewery(typed)
        assert verdicts(report) == [("Brasserie du Coin", "PROBABLE")] and report.level == PROBABLE and report.token

    @pytest.mark.parametrize("typed", ["Brasserie du Port", "Brasserie Parisienne du Canal", "Zythos", ""])
    def test_other_breweries_are_distinct(self, coin, typed):
        assert cm.find_brewery(typed).candidates == () and cm.find_brewery(typed).level == NONE

    def test_a_typo_in_a_long_name_is_caught(self):
        f.make_brewery(name="Brasserie Parisienne")
        assert verdicts(cm.find_brewery("Brasserie Parisiene")) == [("Brasserie Parisienne", "PROBABLE")]

    def test_the_best_candidates_come_first_and_are_bounded(self):
        for index in range(15):
            f.make_brewery(name=f"Brasserie du Coin {index}")
        exact = f.make_brewery(name="Brasserie du Coin")
        report = cm.find_brewery("Brasserie du Coin")
        assert report.candidates[0].obj == exact and len(report.candidates) <= cm.PLACE_CANDIDATES


class TestFindBeer:
    @pytest.fixture
    def punk(self, coin):
        return f.make_beer(name="Punk IPA", brewery=coin)

    @pytest.mark.parametrize("typed", ["Punk IPA", "punk i.p.a.", "PUNK IPA 33cl", "Punk IPA 5,6%", "IPA Punk", "Brasserie du Coin Punk IPA", "Bière Punk IPA"])
    def test_the_same_beer_in_the_same_brewery_is_the_same(self, punk, coin, typed):
        report = cm.find_beer(typed, coin.name, {coin.pk})
        assert verdicts(report) == [("Punk IPA", "SAME")] and report.level == SAME

    @pytest.mark.parametrize("typed", ["Punk IPAA", "Punk IPA Elvis"])
    def test_a_close_name_in_the_same_brewery_is_probable_only_for_a_typo(self, punk, coin, typed):
        report = cm.find_beer(typed, coin.name, {coin.pk})
        assert report.level == (PROBABLE if typed == "Punk IPAA" else NONE)

    def test_the_same_name_at_another_brewery_is_only_information(self, punk, coin):
        other = f.make_brewery(name="Brasserie du Port")
        report = cm.find_beer("Punk IPA", other.name, {other.pk})
        assert verdicts(report) == [("Punk IPA", "ELSEWHERE")] and report.level == NONE and not report.token and report.same is None

    def test_without_a_known_brewery_nothing_blocks(self, punk):
        assert cm.find_beer("Punk IPA", "Brasserie Inconnue", set()).level == NONE

    @pytest.mark.parametrize("typed", ["Stout", "Houblon 2", "Blonde", "Pale Ale"])
    def test_different_beers_stay_distinct(self, coin, typed):
        f.make_beer(name="Imperial Stout", brewery=coin), f.make_beer(name="Houblon 1", brewery=coin), f.make_beer(name="Blanche", brewery=coin)
        assert cm.find_beer(typed, coin.name, {coin.pk}).level == NONE

    def test_the_edited_beer_does_not_match_itself(self, punk, coin):
        assert cm.find_beer("Punk IPA", coin.name, {coin.pk}, exclude_pk=punk.pk).candidates == ()

    def test_deleted_beers_are_ignored(self, punk, coin):
        Beer.objects.filter(pk=punk.pk).update(is_deleted=True)
        assert cm.find_beer("Punk IPA", coin.name, {coin.pk}).candidates == ()

    def test_blank_names_match_nothing(self, coin):
        assert cm.find_beer("", coin.name, {coin.pk}).candidates == () and cm.find_beer("!!!", coin.name, {coin.pk}).candidates == ()


class TestConfirmationTokens:
    def test_a_token_issued_for_this_entry_confirms_it(self, coin):
        report = cm.find_brewery("Microbrasserie du Coin")
        assert cm.confirmed(report, report.token)

    @pytest.mark.parametrize("bad", ["", "garbage", "a:b:c", "x" * 700])
    def test_forged_tokens_are_refused(self, coin, bad):
        assert not cm.confirmed(cm.find_brewery("Microbrasserie du Coin"), bad)

    def test_a_token_for_another_name_is_refused(self, coin):
        token = cm.find_brewery("Microbrasserie du Coin").token
        assert not cm.confirmed(cm.find_brewery("Du Coin Brewing"), token)

    def test_a_token_for_another_kind_is_refused(self, coin):
        f.make_beer(name="Punk IPA", brewery=coin)
        beer_report = cm.find_beer("Punk IPAA", coin.name, {coin.pk})
        assert beer_report.token and not cm.confirmed(cm.find_brewery("Microbrasserie du Coin"), beer_report.token)

    def test_a_token_stops_working_when_the_candidates_change(self, coin):
        report = cm.find_brewery("Microbrasserie du Coin")
        f.make_brewery(name="Les Brasseurs du Coin")
        assert not cm.confirmed(cm.find_brewery("Microbrasserie du Coin"), report.token)

    def test_an_expired_token_is_refused(self, coin, monkeypatch):
        report = cm.find_brewery("Microbrasserie du Coin")
        monkeypatch.setattr(cm, "TOKEN_MAX_AGE", -1)
        assert not cm.confirmed(report, report.token)

    def test_a_token_signed_for_another_purpose_is_refused(self, coin):
        report = cm.find_brewery("Microbrasserie du Coin")
        assert not cm.confirmed(report, signing.dumps({"kind": "brewery", "key": report.key, "ids": [coin.pk]}, salt="other-purpose"))

    def test_no_token_without_a_probable_candidate(self, coin):
        assert cm.find_brewery("Brasserie du Coin").token == "" and cm.find_brewery("Zythos").token == ""
        assert not cm.confirmed(cm.find_brewery("Brasserie du Coin"), "anything")


class TestDecide:
    @pytest.fixture
    def punk(self, coin):
        return f.make_beer(name="Punk IPA", brewery=coin)

    def test_a_new_beer_at_a_new_brewery_goes_through(self):
        inspection = cm.decide("Nouvelle Blonde", "Zythos")
        assert inspection.reusable_brewery is None

    def test_an_identical_brewery_is_reused_without_asking(self, coin):
        assert cm.decide("Nouvelle Blonde", "LA BRASSERIE DU COIN").reusable_brewery == coin

    def test_a_probable_brewery_must_be_chosen_or_confirmed(self, coin):
        with pytest.raises(cm.DuplicateFound) as raised:
            cm.decide("Nouvelle Blonde", "Microbrasserie du Coin")
        assert "Brasserie du Coin" in raised.value.messages[0] and raised.value.inspection.brewery.token

    def test_confirming_that_the_brewery_is_different_lets_it_through_as_a_new_brewery(self, coin):
        token = cm.find_brewery("Microbrasserie du Coin").token
        assert cm.decide("Nouvelle Blonde", "Microbrasserie du Coin", confirm_brewery=token).reusable_brewery is None

    def test_a_confirmed_other_brewery_is_not_compared_with_the_beers_of_the_lookalike(self, punk):
        token = cm.find_brewery("Microbrasserie du Coin").token
        assert cm.decide("Punk IPA", "Microbrasserie du Coin", confirm_brewery=token).reusable_brewery is None

    def test_the_same_beer_in_a_lookalike_brewery_is_caught_before_confirmation(self, punk):
        with pytest.raises(cm.DuplicateFound) as raised:
            cm.decide("Punk IPA", "Microbrasserie du Coin")
        assert len(raised.value.messages) == 2  # la brasserie ET la bière

    def test_the_same_beer_in_the_same_brewery_is_refused_whatever_the_token(self, punk):
        with pytest.raises(cm.DuplicateFound) as raised:
            cm.decide("punk i.p.a.", "Brasserie du Coin", confirm_beer="anything")
        assert "Cette bière existe déjà" in raised.value.messages[0] and "Punk IPA" in raised.value.messages[0]

    def test_a_probable_beer_can_be_confirmed(self, punk):
        with pytest.raises(cm.DuplicateFound):
            cm.decide("Punk IPAA", "Brasserie du Coin")
        token = cm.inspect("Punk IPAA", "Brasserie du Coin").beer.token
        assert cm.decide("Punk IPAA", "Brasserie du Coin", confirm_beer=token)

    def test_a_beer_token_does_not_work_for_another_name(self, punk):
        token = cm.inspect("Punk IPAA", "Brasserie du Coin").beer.token
        with pytest.raises(cm.DuplicateFound):
            cm.decide("Punk IPAAA", "Brasserie du Coin", confirm_beer=token)

    def test_the_same_name_at_another_brewery_is_allowed(self, punk):
        assert cm.decide("Punk IPA", "Brasserie du Port")

    def test_editing_a_beer_does_not_collide_with_itself(self, punk):
        assert cm.decide("Punk IPA", "Brasserie du Coin", exclude_beer_pk=punk.pk)


class TestExistingDuplicates:
    def test_breweries_pairs(self, coin):
        f.make_brewery(name="Microbrasserie du Coin")
        f.make_brewery(name="La Brasserie Du Coin SAS")
        f.make_brewery(name="Brasserie du Port")
        pairs = cm.duplicate_breweries()
        assert {(p.first.name, p.second.name, p.level.name) for p in pairs} == {
            ("Brasserie du Coin", "Microbrasserie du Coin", "PROBABLE"), ("Brasserie du Coin", "La Brasserie Du Coin SAS", "SAME"),
            ("Microbrasserie du Coin", "La Brasserie Du Coin SAS", "PROBABLE"),
        }
        assert pairs[0].level == SAME  # les identiques d'abord

    def test_beer_pairs_only_within_a_brewery(self, coin):
        first = f.make_beer(name="Punk IPA", brewery=coin)
        second = f.make_beer(name="PUNK I.P.A. 33cl", brewery=coin)
        f.make_beer(name="Punk IPA", brewery=f.make_brewery(name="Brasserie du Port"))
        f.make_beer(name="Stout", brewery=coin)
        pairs = cm.duplicate_beers()
        assert [(p.first, p.second, p.level) for p in pairs] == [(first, second, SAME)]

    def test_deleted_beers_are_not_listed(self, coin):
        f.make_beer(name="Punk IPA", brewery=coin)
        gone = f.make_beer(name="Punk I.P.A", brewery=coin)
        Beer.objects.filter(pk=gone.pk).update(is_deleted=True)
        assert cm.duplicate_beers() == []

    def test_the_list_is_bounded(self, coin, monkeypatch):
        monkeypatch.setattr(cm, "MAX_PAIRS", 2)
        for index in range(4):
            f.make_brewery(name=f"Brasserie Alpha {index % 2}{' ' * index}")
        assert len(cm.duplicate_breweries()) <= 2
