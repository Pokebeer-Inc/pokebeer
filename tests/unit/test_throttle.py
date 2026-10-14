"""Limitation de débit : règles, IP du visiteur et absence de donnée personnelle en base."""
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import RequestFactory
from django.utils import timezone

from app.models import ThrottleHit
from app.services.protection import throttle
from app.services.protection.throttle import Rule

pytestmark = pytest.mark.django_db

RULE = Rule("test", 3, timedelta(minutes=10))


class TestRule:
    def test_blocks_once_the_limit_is_reached(self):
        for _ in range(2):
            RULE.record("1.1.1.1")
        assert not RULE.exceeded("1.1.1.1")
        RULE.record("1.1.1.1")
        assert RULE.exceeded("1.1.1.1")

    def test_keys_and_scopes_are_independent(self):
        for _ in range(3):
            RULE.record("1.1.1.1")
        assert not RULE.exceeded("2.2.2.2")
        assert not Rule("other", 3, timedelta(minutes=10)).exceeded("1.1.1.1")

    def test_old_attempts_leave_the_window(self):
        for _ in range(3):
            RULE.record("1.1.1.1")
        ThrottleHit.objects.update(created_at=timezone.now() - timedelta(minutes=11))
        assert not RULE.exceeded("1.1.1.1")

    def test_reset_clears_the_counter(self):
        for _ in range(3):
            RULE.record("alice")
        RULE.reset("alice")
        assert not RULE.exceeded("alice")

    def test_keys_are_case_insensitive(self):
        for _ in range(3):
            RULE.record("Alice")
        assert RULE.exceeded("aLICE")

    def test_expired_rows_are_purged(self):
        RULE.record("old")
        ThrottleHit.objects.update(created_at=timezone.now() - throttle.RETENTION - timedelta(minutes=1))
        RULE.record("new")
        assert ThrottleHit.objects.count() == 1

    def test_keys_are_stored_hashed(self):
        RULE.record("alice@203.0.113.7")
        stored = ThrottleHit.objects.get()
        assert "alice" not in stored.key_hash and "203.0.113.7" not in stored.key_hash and len(stored.key_hash) == 64


class TestAtomicHit:
    def test_admits_until_the_limit_then_counts_nothing_more(self):
        assert [RULE.hit("1.1.1.1") for _ in range(4)] == [True, True, True, False]
        assert ThrottleHit.objects.count() == RULE.attempts

    def test_release_gives_back_the_last_attempt(self):
        for _ in range(3):
            RULE.hit("1.1.1.1")
        RULE.release("1.1.1.1")
        assert RULE.hit("1.1.1.1") and not RULE.hit("1.1.1.1")

    def test_release_only_touches_its_own_key(self):
        RULE.hit("1.1.1.1")
        RULE.release("2.2.2.2")
        assert ThrottleHit.objects.count() == 1

    def test_the_check_and_the_count_hold_a_lock_on_the_key(self):
        # Verrou consultatif pris AVANT le comptage : pas de fenêtre entre la vérification et l'écriture pour deux requêtes simultanées
        with CaptureQueriesContext(connection) as captured:
            RULE.hit("1.1.1.1")
        sql = [query["sql"] for query in captured.captured_queries]
        lock = next(i for i, query in enumerate(sql) if "pg_advisory_xact_lock" in query)
        assert lock < next(i for i, query in enumerate(sql) if "COUNT" in query.upper())


class TestClientIp:
    def request(self, **meta):
        return RequestFactory().get("/", **meta)

    def test_uses_remote_addr_without_proxy_header(self):
        assert throttle.client_ip(self.request(REMOTE_ADDR="9.9.9.9")) == "9.9.9.9"

    def test_trusts_only_the_last_proxy_entry(self, settings):
        settings.TRUSTED_PROXY_COUNT = 1
        request = self.request(HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.7", REMOTE_ADDR="10.0.0.1")
        assert throttle.client_ip(request) == "203.0.113.7"

    def test_spoofed_header_cannot_choose_the_key(self, settings):
        settings.TRUSTED_PROXY_COUNT = 1
        first = self.request(HTTP_X_FORWARDED_FOR="1.1.1.1, 203.0.113.7")
        second = self.request(HTTP_X_FORWARDED_FOR="2.2.2.2, 203.0.113.7")
        assert throttle.client_ip(first) == throttle.client_ip(second)

    def test_ignores_the_header_when_no_proxy_is_trusted(self, settings):
        settings.TRUSTED_PROXY_COUNT = 0
        assert throttle.client_ip(self.request(HTTP_X_FORWARDED_FOR="6.6.6.6", REMOTE_ADDR="9.9.9.9")) == "9.9.9.9"
