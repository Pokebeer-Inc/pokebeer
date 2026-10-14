"""Garde-fous globaux : configuration Django, migrations et routage."""
from io import StringIO
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.urls import URLPattern, get_resolver, reverse

from app.models import BeerUser


def test_system_checks_pass():
    call_command("check", stdout=StringIO())


@pytest.mark.django_db
def test_models_and_migrations_are_in_sync():
    call_command("makemigrations", "--check", "--dry-run", stdout=StringIO())


def test_generated_static_files_are_not_versioned():
    """staticfiles/ (collectstatic) est produit par le déploiement : le versionner réintroduirait des copies obsolètes des sources."""
    ignored = Path(settings.BASE_DIR, ".gitignore").read_text().splitlines()
    assert "staticfiles/" in ignored


def test_vercel_receives_the_generated_static_files():
    """Un .vercelignore remplace .gitignore pour l'envoi à Vercel : il ne doit pas exclure les fichiers que le déploiement génère."""
    ignored = Path(settings.BASE_DIR, ".vercelignore").read_text().splitlines()
    assert "staticfiles/" not in ignored and ".env" in ignored and "media/" in ignored


def test_every_app_route_is_named():
    patterns = get_resolver("app.urls").url_patterns
    assert [str(p.pattern) for p in patterns if isinstance(p, URLPattern) and not p.name] == []


@pytest.mark.django_db
class TestUserManager:
    def test_create_user_builds_a_plain_contributor(self):
        user = BeerUser.objects.create_user("managed", email="managed@EXAMPLE.test", password="x")
        assert user.check_password("x") and user.email == "managed@example.test"
        assert user.groups.filter(name="Contributeur").exists() and not (user.is_staff or user.is_superuser)

    def test_create_superuser_joins_the_staff_group(self):
        user = BeerUser.objects.create_superuser("root", email="root@example.test", password="x")
        assert user.is_superuser and user.is_staff

    def test_created_superuser_can_open_the_admin(self, client):
        BeerUser.objects.create_superuser("root", email="root@example.test", password="Pokebeer-Test-2026!")
        client.login(username="root", password="Pokebeer-Test-2026!")
        assert client.get(reverse("admin:index")).status_code == 200

    @pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
    def test_superuser_flags_cannot_be_disabled(self, flag):
        with pytest.raises(ValueError):
            BeerUser.objects.create_superuser("root", email="root@example.test", password="x", **{flag: False})

    def test_createsuperuser_command_works(self):
        call_command("createsuperuser", interactive=False, username="cli", email="cli@example.test", stdout=StringIO())
        assert BeerUser.objects.get(username="cli").is_staff

    def test_username_is_required(self):
        with pytest.raises(ValueError):
            BeerUser.objects.create_user("", email="nobody@example.test")


def test_every_model_is_reexported_by_the_models_package():
    """`from app.models import X` doit toujours fonctionner : un nouveau modèle se déclare dans un module de app/models/ ET dans __init__."""
    from django.apps import apps

    import app.models as models_package

    missing = [model.__name__ for model in apps.get_app_config("app").get_models() if getattr(models_package, model.__name__, None) is not model]
    assert not missing, missing


def test_no_scratch_test_files_are_left_in_the_suite():
    """Les fichiers de débogage (test_tmp_*, test_dbg_*, test_probe_*) ne doivent pas rester dans tests/."""
    scratch = [str(p) for p in Path(settings.BASE_DIR, "tests").rglob("test_*.py") if any(word in p.stem for word in ("tmp", "dbg", "probe"))]
    assert not scratch, f"fichiers de test temporaires : {scratch}"
