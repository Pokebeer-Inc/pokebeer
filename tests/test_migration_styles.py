"""Migrations 0098 à 0100 : familles en table, styles liés aux bières, référentiel élargi ; marche arrière comprise."""
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture
def at_0097():
    apps = migrate([("app", "0097_beer_without_brewery")])
    yield apps
    migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())  # laisse la base à jour pour les autres tests


def seed(apps):
    Style, Brewery, Beer = (apps.get_model("app", name) for name in ("Style", "Brewery", "Beer"))
    # Les tables sont vidées entre deux tests de ce type : on recrée ce que la migration 0094 y avait semé
    Style.objects.update_or_create(name="Stout", defaults={"family": "Brune, porter et stout", "aliases": "Dry Stout"})
    Style.objects.update_or_create(name="IPA", defaults={"family": "IPA", "aliases": "India Pale Ale"})
    brewery = Brewery.objects.create(name="Brasserie", slug="brasserie-s", description="d")
    kinds = {"stout": "dry stout, Mystère", "none": None, "empty": "", "ipa": "IPA", "weird": "Fruitée à la rhubarbe"}
    return {key: Beer.objects.create(name=key, slug=f"{key}-s", brewery=brewery, style=value, style_family="Brune, porter et stout" if key == "stout" else "")
            for key, value in kinds.items()}


def test_families_become_a_table_and_beers_get_their_styles(at_0097):
    beers = seed(at_0097)

    apps = migrate([("app", "0099_beer_style_structure")])

    StyleFamily, Style, Beer = apps.get_model("app", "StyleFamily"), apps.get_model("app", "Style"), apps.get_model("app", "Beer")
    assert Style.objects.get(name="Stout").family.name == "Brune, porter et stout" and StyleFamily.objects.filter(name="IPA").count() == 1
    stout = Beer.objects.get(pk=beers["stout"].pk)
    assert stout.style == "Stout, Mystère" and stout.primary_style.name == "Stout"
    assert list(stout.beer_styles.order_by("position").values_list("style__name", flat=True)) == ["Stout", "Mystère"]
    pending = Style.objects.get(name="Mystère")
    assert not pending.is_official and pending.family is None
    assert Beer.objects.get(pk=beers["weird"].pk).primary_style.name == "Fruitée à la rhubarbe"  # sans style reconnu : le premier
    assert not Beer.objects.get(pk=beers["none"].pk).beer_styles.exists() and Beer.objects.get(pk=beers["none"].pk).style is None
    assert Beer.objects.get(pk=beers["empty"].pk).primary_style is None


def test_the_extended_catalog_adopts_pending_styles_and_merges_aliases(at_0097):
    seed(at_0097)
    apps = migrate([("app", "0099_beer_style_structure")])
    Beer, Style = apps.get_model("app", "Beer"), apps.get_model("app", "Style")
    brewery = apps.get_model("app", "Brewery").objects.get()
    Beer.objects.create(name="Kriek maison", slug="kriek-s", brewery=brewery, style="Cerise")  # sera un alias de Kriek
    Beer.objects.create(name="Lambic maison", slug="lambic-s", brewery=brewery, style="Lambic")  # style à valider qui entre au référentiel
    migrate([("app", "0099_beer_style_structure")])

    apps = migrate([("app", "0100_extended_style_catalog")])

    Beer, Style = apps.get_model("app", "Beer"), apps.get_model("app", "Style")
    assert Style.objects.filter(is_official=True).count() >= 90
    assert Beer.objects.get(slug="lambic-s").primary_style.family.name == "Lambic et fermentation spontanée"
    assert not Style.objects.filter(name="Lambic", is_official=False).exists()
    assert Style.objects.get(name="Mystère").beer_styles.count() == 1  # un style inconnu reste à valider


def test_going_back_restores_the_family_texts(at_0097):
    seed(at_0097)
    apps = migrate([("app", "0100_extended_style_catalog")])
    stout = apps.get_model("app", "Beer").objects.get(slug="stout-s")
    assert stout.primary_style.family.name == "Brune, porter et stout"

    apps = migrate([("app", "0097_beer_without_brewery")])

    Beer, Style = apps.get_model("app", "Beer"), apps.get_model("app", "Style")
    assert Beer.objects.get(slug="stout-s").style_family == "Brune, porter et stout"
    assert Style.objects.get(name="Stout").family == "Brune, porter et stout" and not Style.objects.filter(family="").exists()
