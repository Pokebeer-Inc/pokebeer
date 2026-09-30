"""Garde-fous globaux : configuration Django, migrations et routage."""
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import URLPattern, get_resolver, reverse

from app.models import BeerUser


def test_system_checks_pass():
    call_command("check", stdout=StringIO())


@pytest.mark.django_db
def test_models_and_migrations_are_in_sync():
    call_command("makemigrations", "--check", "--dry-run", stdout=StringIO())


def test_every_app_route_is_named():
    patterns = get_resolver("app.urls").url_patterns
    assert [str(p.pattern) for p in patterns if isinstance(p, URLPattern) and not p.name] == []


@pytest.mark.django_db
class TestUserManager:
    def test_create_user_builds_a_plain_contributor(self):
        user = BeerUser.objects.create_user("managed", email="managed@EXAMPLE.test", password="x")
        assert user.check_password("x") and user.email == "managed@example.test"
        assert user.is_contributor and not (user.is_staff or user.is_superuser)

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
