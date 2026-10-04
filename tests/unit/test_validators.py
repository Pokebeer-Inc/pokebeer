import pytest
from django.core.exceptions import ValidationError

from app.forms import BarProForm, BeerForm
from app.validators import plain_text_validator, validate_siret
from tests import factories as f


class TestSiret:
    @pytest.mark.parametrize("siret", ["73282932000074", "55203253400646", "35600000000048", "35600000000001"])
    def test_valid_numbers_are_accepted(self, siret):
        validate_siret(siret)

    @pytest.mark.parametrize("siret", ["12345678901234", "7328293200007", "732829320000745", "7328293200007a", "٧٣٢٨٢٩٣٢٠٠٠٠٧٤", "", "73282932 00074"])
    def test_invalid_numbers_are_refused(self, siret):
        with pytest.raises(ValidationError):
            validate_siret(siret)

    @pytest.mark.django_db
    def test_forms_apply_the_check(self):
        data = {"name": "Chez Patron", "siret": "12345678901234", "description": "x"}
        assert "siret" in BarProForm(data=data).errors


class TestPlainText:
    @pytest.mark.parametrize("value", ["Punk IPA", "Brasserie d'Été & Fils", "Ma bière 5 > 4"[:6]])
    def test_plain_names_are_accepted(self, value):
        plain_text_validator(value)

    @pytest.mark.parametrize("value", ["<img src=x onerror=alert(1)>", "a<b", "x>y", "<script>"])
    def test_markup_is_refused(self, value):
        with pytest.raises(ValidationError):
            plain_text_validator(value)

    @pytest.mark.django_db
    @pytest.mark.parametrize("field", ["name", "brewery_name"])
    def test_beer_form_refuses_markup(self, field):
        data = {"name": "Punk IPA", "brewery_name": "BrewDog", "degree": "5.0", **{field: "<b>x</b>"}}
        assert field in BeerForm(data=data, user=f.make_user()).errors

    @pytest.mark.django_db
    def test_models_refuse_markup_when_validated(self):
        brewery = f.make_brewery(name="<img onerror=x>")
        with pytest.raises(ValidationError) as error:
            brewery.full_clean()
        assert "name" in error.value.message_dict
