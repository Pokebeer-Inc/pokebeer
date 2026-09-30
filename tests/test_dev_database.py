import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError

from app.dev_seed.seeder import DevDatabaseSeeder
from app.models import Beer, BeerUser, Drinks
from pokebeer.database import assert_dev_database, get_databases

PROD_URL = "postgresql://postgres.prodref:secret@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
DEV_URL = "postgresql://pokebeer:devpass@localhost:5432/pokebeer_dev"


def test_prod_mode_uses_database_url():
    config = get_databases(debug=False, env={"DATABASE_URL": PROD_URL, "DEV_DATABASE_URL": DEV_URL})["default"]
    assert config["HOST"] == "aws-0-eu-west-1.pooler.supabase.com"


def test_debug_mode_uses_dev_database_url():
    config = get_databases(debug=True, env={"DATABASE_URL": PROD_URL, "DEV_DATABASE_URL": DEV_URL})["default"]
    assert (config["HOST"], config["NAME"]) == ("localhost", "pokebeer_dev")


def test_debug_mode_without_dev_url_never_falls_back_to_prod():
    with pytest.raises(ImproperlyConfigured):
        get_databases(debug=True, env={"DATABASE_URL": PROD_URL})


def test_debug_mode_refuses_dev_url_pointing_to_prod():
    same_db_other_password = PROD_URL.replace("secret", "other")
    with pytest.raises(ImproperlyConfigured):
        get_databases(debug=True, env={"DATABASE_URL": PROD_URL, "DEV_DATABASE_URL": same_db_other_password})


def test_other_supabase_project_on_shared_pooler_is_allowed():
    other_project = PROD_URL.replace("prodref", "devref")
    config = get_databases(debug=True, env={"DATABASE_URL": PROD_URL, "DEV_DATABASE_URL": other_project})["default"]
    assert config["USER"] == "postgres.devref"


def test_destructive_operations_refused_outside_debug():
    with pytest.raises(ImproperlyConfigured):
        assert_dev_database(False, {"HOST": "localhost"}, env={})


def test_seed_command_refused_outside_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_dev_db")


@pytest.mark.django_db
def test_seeder_fills_every_domain():
    counts = DevDatabaseSeeder(password="test-password").run()

    assert counts["BeerUser"] == BeerUser.objects.count() > 0
    assert Beer.objects.filter(embedding__isnull=True).count() == Beer.objects.count() > 0
    assert Drinks.objects.exists()
    brewer = BeerUser.objects.get(username="brasseur_dev")
    assert brewer.is_brewer and brewer.is_contributor
    assert BeerUser.objects.get(username="admin_dev").check_password("test-password")
