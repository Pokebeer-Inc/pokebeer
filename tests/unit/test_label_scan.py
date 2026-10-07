"""Validation de la réponse de l'IA pour l'analyse d'étiquette."""
import json

import pytest

from app.services import label_scan


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
