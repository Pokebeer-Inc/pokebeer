import re
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from app.context_processors import supabase_config
from app.services.messaging.security import get_secure_channel_name

CHANNEL_PATTERN = re.compile(r"^room_[0-9a-f]{32}$")


def member(pk, password="hash-a"):
    return SimpleNamespace(pk=pk, password=password)


class TestSecureChannelName:
    def test_format_is_128_bits_without_user_id(self):
        assert CHANNEL_PATTERN.match(get_secure_channel_name(member(42)))

    def test_is_deterministic(self):
        assert get_secure_channel_name(member(7)) == get_secure_channel_name(member(7))

    def test_differs_between_users(self):
        assert len({get_secure_channel_name(member(pk)) for pk in range(1, 200)}) == 199

    def test_depends_on_secret_key(self, settings):
        before = get_secure_channel_name(member(1))
        settings.SECRET_KEY = "another-secret-key"
        assert get_secure_channel_name(member(1)) != before

    def test_changes_with_the_password_so_a_leaked_name_stops_working(self):
        assert get_secure_channel_name(member(1, "hash-a")) != get_secure_channel_name(member(1, "hash-b"))


class TestSupabaseContextProcessor:
    def _context(self, user):
        request = RequestFactory().get("/")
        request.user = user
        return supabase_config(request)

    def test_anonymous_gets_public_keys_only(self, settings):
        settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY = "https://x.supabase.co", "anon"
        assert self._context(AnonymousUser()) == {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "anon"}

    @pytest.mark.django_db
    def test_authenticated_user_gets_his_private_channel(self, user):
        assert self._context(user)["WS_CHANNEL_NAME"] == get_secure_channel_name(user)

    @pytest.mark.django_db
    def test_service_role_key_is_never_exposed(self, settings, user):
        settings.SUPABASE_SERVICE_ROLE_KEY = "service-role-secret"
        assert "service-role-secret" not in self._context(user).values()
