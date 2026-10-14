"""Sens des dépendances et répartition des rôles : domaine <- modèles <- services <- vues."""
import re
from pathlib import Path

import pytest
from django.conf import settings

from app.models import CustomNotebook
from app.services.catalog import notebooks
from app.forms import CustomNotebookForm
from tests import factories as f

APP = Path(settings.BASE_DIR, "app")


def imports_of(path):
    return [line for line in path.read_text().splitlines() if line.startswith(("import ", "from "))]


@pytest.mark.parametrize("path", sorted((APP / "models").glob("*.py")) + sorted((APP / "domain").glob("*.py")), ids=lambda p: p.name)
def test_models_and_domain_never_import_services(path):
    assert not any("services" in line for line in imports_of(path))


@pytest.mark.parametrize("path", sorted((APP / "domain").glob("*.py")), ids=lambda p: p.name)
def test_the_domain_never_imports_models(path):
    assert not any(re.search(r"\bmodels\b", line) and "django.db" not in line for line in imports_of(path))


@pytest.mark.parametrize("path", sorted((APP / "views").glob("*.py")), ids=lambda p: p.name)
def test_views_leave_notifications_and_trophies_to_the_services(path):
    source = path.read_text()
    assert "notify(" not in source and "check_and_notify_achievements" not in source


@pytest.mark.django_db
class TestNotebookLimit:
    def test_the_limit_is_enforced_by_the_service(self, user):
        CustomNotebook.objects.bulk_create([CustomNotebook(user=user, title=f"C{i}", slug=f"c{i}") for i in range(notebooks.MAX_NOTEBOOKS)])
        with pytest.raises(notebooks.NotebookLimitReached):
            notebooks.create(user, CustomNotebookForm({"title": "Un de trop"}))
        assert user.custom_notebooks.count() == notebooks.MAX_NOTEBOOKS

    def test_only_own_tastings_are_added(self, user, other_user):
        mine, theirs = f.make_drink(user), f.make_drink(other_user)
        form = CustomNotebookForm({"title": "Été"})
        assert form.is_valid()
        notebook = notebooks.create(user, form, [mine.slug, theirs.slug])
        assert list(notebook.drinks.all()) == [mine]
