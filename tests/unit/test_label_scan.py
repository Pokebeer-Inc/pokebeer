"""Validation de la réponse de l'IA pour l'analyse d'étiquette."""
import json

import pytest
from decimal import Decimal

from app.services.catalog import label_scan


def answer(**fields):
    return json.dumps({"found": True, "name": "Punk IPA", **fields})


class TestParse:
    def test_a_complete_answer_is_normalised(self):
        label = label_scan.parse(answer(brewery=" BrewDog ", style="IPA", degree="5,6", bitterness=35.0))
        assert label == {"name": "Punk IPA", "brewery": "BrewDog", "style": "IPA", "degree": 5.6, "bitterness": 35}

    def test_markdown_fences_are_ignored(self):
        assert label_scan.parse("```json\n" + answer() + "\n```")["name"] == "Punk IPA"

    @pytest.mark.parametrize("raw", ['{"found": false, "name": "X"}', '{"found": true}', '{"found": true, "name": "   "}', '{"name": "X"}', '{"found": 1, "name": "X"}'])
    def test_no_identified_beer_gives_none(self, raw):
        assert label_scan.parse(raw) is None

    @pytest.mark.parametrize("raw", ["Je ne sais pas", "", "[]", '"text"', "null", "{broken"])
    def test_unusable_answers_raise(self, raw):
        with pytest.raises(ValueError):
            label_scan.parse(raw)

    @pytest.mark.parametrize("value, expected", [
        (5.5, 5.5), ("5.55", 5.6), ("5,5", 5.5), (0, 0.0), (100, 100.0), (101, None), (-1, None), ("abc", None), (None, None),
        (True, None), ("NaN", None), ("Infinity", None), ([5], None), ({"a": 1}, None),
    ])
    def test_degree_is_a_bounded_number(self, value, expected):
        assert label_scan.parse(answer(degree=value))["degree"] == expected

    @pytest.mark.parametrize("value, expected", [(35, 35), ("35", 35), (35.9, 35), (500, 500), (501, None), (-5, None), ("x", None), (True, None)])
    def test_bitterness_is_a_bounded_integer(self, value, expected):
        assert label_scan.parse(answer(bitterness=value))["bitterness"] == expected

    def test_markup_is_stripped_and_text_is_bounded(self):
        label = label_scan.parse(answer(name="<b>Stout</b>\n\t  Noire", brewery="x" * 1000, style=["IPA"]))
        assert label["name"] == "bStout/b Noire" and len(label["brewery"]) == 150 and label["style"] is None

    def test_unknown_keys_never_reach_the_form(self):
        assert set(label_scan.parse(answer(admin=True, is_staff=True))) == {"name", "brewery", "style", "degree", "bitterness"}


@pytest.mark.django_db
class TestAnalyze:
    """Ce qui est imprimé sur l'étiquette prime ; le catalogue et le web ne font que combler, et jamais sans preuve."""

    @pytest.fixture
    def client(self):
        from tests.fakes import mistral
        return mistral()

    def read(self, client, vision, web=None, reserve=lambda model: True):
        from tests.fakes import chat_reply, search_reply
        client.chat.complete.return_value = chat_reply(json.dumps(vision))
        if web is not None:
            client.beta.conversations.start.return_value = web if not isinstance(web, dict) else search_reply(json.dumps(web))
        return label_scan.analyze(client, b"image", reserve)

    PRINTED = {"found": True, "name": "Punk IPA", "brewery": "BrewDog", "style": None, "degree": 5.6, "bitterness": None}
    WEB = {"found": True, "name": "Punk IPA", "brewery": "BrewDog", "style": "IPA", "degree": 5.6, "bitterness": 35}

    def test_the_prompt_forbids_guessing_what_is_not_printed(self):
        prompt = label_scan.PROMPT.lower()
        assert "n'invente rien" in prompt and "utilise tes connaissances" not in prompt and "déduis" not in prompt

    def test_the_web_corrects_the_style_and_completes_the_ibu_and_says_so(self, client):
        reading = self.read(client, {**self.PRINTED, "style": "Ale"}, self.WEB)
        assert reading.label["style"] == "IPA" and reading.corrected_by_web == ("style",)
        assert reading.label["bitterness"] == 35 and reading.from_web == ("bitterness",)

    def test_the_printed_degree_always_wins_over_the_web(self, client):
        reading = self.read(client, self.PRINTED, {**self.WEB, "degree": 4.0})
        assert reading.label["degree"] == 5.6 and "degree" not in reading.corrected_by_web

    def test_the_web_only_completes_a_degree_that_is_not_printed(self, client):
        reading = self.read(client, {**self.PRINTED, "degree": None}, self.WEB)
        assert reading.label["degree"] == 5.6 and "degree" in reading.from_web

    def test_the_brewery_spelling_is_corrected_by_the_web(self, client):
        reading = self.read(client, {**self.PRINTED, "brewery": "Ours Doré"}, {**self.WEB, "brewery": "Brasserie de l'Ours Doré"})
        assert reading.label["brewery"] == "Brasserie de l'Ours Doré" and "brewery" in reading.corrected_by_web

    def test_the_name_read_on_the_image_is_never_changed(self, client):
        reading = self.read(client, {**self.PRINTED, "name": "Punk IPAA"}, self.WEB)
        assert reading.label["name"] == "Punk IPAA" and "name" not in reading.corrected_by_web + reading.from_web

    def test_without_a_brewery_on_the_label_the_web_provides_it(self, client):
        reading = self.read(client, {**self.PRINTED, "brewery": None}, self.WEB)
        assert reading.label["brewery"] == "BrewDog" and "brewery" in reading.from_web

    def test_an_ambiguous_name_without_brewery_is_not_resolved_by_guessing(self, client):
        reading = self.read(client, {**self.PRINTED, "brewery": None}, {**self.WEB, "found": False})
        assert reading.label["brewery"] is None and reading.from_web == ()

    def test_a_confirmation_changes_nothing(self, client):
        reading = self.read(client, {**self.PRINTED, "style": "IPA", "bitterness": 35}, self.WEB)
        assert reading.label == {"name": "Punk IPA", "brewery": "BrewDog", "style": "IPA", "degree": 5.6, "bitterness": 35}
        assert reading.from_web == () and reading.corrected_by_web == ()
        client.beta.conversations.start.assert_called_once()

    def test_a_missing_value_from_the_web_never_erases_what_was_read(self, client):
        reading = self.read(client, self.PRINTED, {**self.WEB, "degree": None, "style": None, "bitterness": None})
        assert reading.label["degree"] == 5.6 and reading.corrected_by_web == ()

    def test_the_search_receives_only_validated_text_never_the_photo(self, client):
        self.read(client, self.PRINTED, self.WEB)
        sent = client.beta.conversations.start.call_args.kwargs["inputs"]
        assert json.loads(sent) == {"name": "Punk IPA", "brewery": "BrewDog", "degree": 5.6}

    def test_a_correction_needs_the_same_proofs_as_a_completion(self, client):
        reading = self.read(client, {**self.PRINTED, "style": "Ale"}, {**self.WEB, "brewery": "Brasserie du Coin"})
        assert reading.label["style"] == "Ale" and reading.corrected_by_web == ()

    def test_an_answer_without_a_cited_source_is_ignored(self, client):
        from types import SimpleNamespace
        no_source = SimpleNamespace(outputs=[SimpleNamespace(type="message.output", content=[SimpleNamespace(type="text", text=json.dumps(self.WEB))])])
        reading = self.read(client, self.PRINTED, no_source)
        assert reading.label["style"] is None and reading.from_web == ()

    def test_a_source_that_is_not_https_does_not_count(self, client):
        from types import SimpleNamespace
        weak = SimpleNamespace(outputs=[SimpleNamespace(type="message.output", content=[
            SimpleNamespace(type="text", text=json.dumps(self.WEB)), SimpleNamespace(type="tool_reference", url="http://example.org")])])
        assert self.read(client, self.PRINTED, weak).from_web == ()

    @pytest.mark.parametrize("answer", [
        {"name": "Tout autre chose", "brewery": "BrewDog"},        # une autre bière
        {"name": "Punk IPA", "brewery": "Brasserie du Coin"},      # même nom chez une autre brasserie
        {"name": "Punk IPA", "brewery": None},                     # brasserie non confirmée
        {"found": False, "name": "Punk IPA", "brewery": "BrewDog"},  # le web ne l'a pas trouvée
    ])
    def test_an_answer_about_another_beer_is_ignored_as_a_whole(self, client, answer):
        reading = self.read(client, self.PRINTED, {**self.WEB, **answer})
        assert reading.label["style"] is None and reading.label["bitterness"] is None and reading.from_web == ()

    def test_a_close_spelling_of_the_same_beer_is_accepted(self, client):
        reading = self.read(client, self.PRINTED, {**self.WEB, "name": "PUNK IPA", "brewery": "Brewdog Brewery"})
        assert reading.label["style"] == "IPA"

    def test_implausible_values_are_dropped_not_proposed(self, client):
        reading = self.read(client, {**self.PRINTED, "degree": None}, {**self.WEB, "degree": 60, "bitterness": 900})
        assert reading.label["degree"] is None and reading.label["bitterness"] is None and reading.label["style"] == "IPA"

    def test_a_failing_or_spent_search_keeps_the_reading(self, client):
        client.beta.conversations.start.side_effect = RuntimeError("down")
        assert self.read(client, self.PRINTED).label["style"] is None
        assert self.read(client, self.PRINTED, reserve=lambda model: model == label_scan.settings.LABEL_VISION_MODEL).from_web == ()

    def test_a_beer_unreadable_on_the_image_is_not_searched(self, client):
        assert self.read(client, {"found": False}) is None
        client.beta.conversations.start.assert_not_called()

    @pytest.mark.django_db
    def test_the_catalogue_completes_a_known_beer(self, client):
        from tests import factories as f
        brewery = f.make_brewery(name="BrewDog")
        f.make_beer(name="Punk IPA", brewery=brewery, style="IPA", degree=Decimal("5.6"), bitterness=35)
        reading = self.read(client, self.PRINTED, self.WEB)
        assert reading.label["style"] == "IPA" and reading.label["bitterness"] == 35 and reading.from_catalogue == ("style", "bitterness")

    @pytest.mark.django_db
    def test_the_same_name_in_another_brewery_is_not_borrowed_from_the_catalogue(self, client):
        from tests import factories as f
        f.make_beer(name="Punk IPA", brewery=f.make_brewery(name="Brasserie du Coin"), style="Stout", bitterness=80)
        assert self.read(client, self.PRINTED).from_catalogue == ()
