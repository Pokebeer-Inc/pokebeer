"""Migration 0086 : fusion des notes en double, trophées rangés par identifiant, refus des signalements sans cible unique."""
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("app", "0085_moderation_suggestions")]
AFTER = [("app", "0086_integrity_achievement_slugs_and_indexes")]

pytestmark = pytest.mark.django_db(transaction=True)


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture
def old_apps():
    apps = migrate(BEFORE)
    yield apps
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
    migrate(latest)  # laisse la base à jour pour les autres tests


def seed(apps):
    User, Brewery, Beer, Drinks = (apps.get_model("app", name) for name in ("BeerUser", "Brewery", "Beer", "Drinks"))
    user = User.objects.create(username="doublon", email="doublon@example.test")
    brewery = Brewery.objects.create(name="Brasserie", slug="brasserie-x", description="d")
    beer = Beer.objects.create(name="Blonde", slug="blonde-x", brewery_id=brewery)
    return user, beer, Drinks


def test_duplicate_tastings_are_merged_and_attached_content_is_kept(old_apps):
    user, beer, Drinks = seed(old_apps)
    first = Drinks.objects.create(drinker_id=user, beer_id=beer, slug="a1", note=5, comment="ancienne", date="2026-01-01")
    Drinks.objects.create(drinker_id=user, beer_id=beer, slug="a2", note=8, comment="récente", date="2026-02-01")
    Notebook = old_apps.get_model("app", "CustomNotebook")
    notebook = Notebook.objects.create(user=user, slug="nb1", title="Carnet")
    notebook.drinks.add(first)
    Report = old_apps.get_model("app", "Report")
    report = Report.objects.create(reporter=user, slug="r1", reported_drink=first, reason="spam", description="x")
    Notification = old_apps.get_model("app", "Notification")
    Notification.objects.create(recipient=user, slug="n1", notif_type="achievement", achievement_name="Juge", text_content="Juge (Bronze)")

    apps = migrate(AFTER)

    Drinks = apps.get_model("app", "Drinks")
    assert list(Drinks.objects.values_list("comment", flat=True)) == ["récente"]
    kept = Drinks.objects.get()
    assert list(kept.notebooks.values_list("title", flat=True)) == ["Carnet"]
    assert apps.get_model("app", "Report").objects.get(pk=report.pk).reported_drink_id == kept.pk
    assert apps.get_model("app", "Notification").objects.get().achievement_slug == "juge"


def test_a_report_without_a_target_stops_the_migration(old_apps):
    user, beer, Drinks = seed(old_apps)
    Report = old_apps.get_model("app", "Report")
    Report.objects.create(reporter=user, slug="r2", reason="spam", description="x")
    with pytest.raises(RuntimeError, match="Signalements sans cible unique"):
        migrate(AFTER)
    Report.objects.all().delete()  # la base doit pouvoir être migrée à la fin du test
