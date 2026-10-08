from datetime import timedelta

import pytest
from django.utils import timezone

from app.models import ChatUsage
from app.services.quota import consume_quota
from tests import factories as f

pytestmark = pytest.mark.django_db

LIMIT = 3


def consume(user, times):
    return [consume_quota(user, LIMIT) for _ in range(times)]


def test_allows_exactly_the_limit_then_refuses(user):
    assert consume(user, LIMIT + 2) == [True] * LIMIT + [False, False]
    assert ChatUsage.objects.get(user=user).count == LIMIT


def test_quota_is_per_user(user, other_user):
    consume(user, LIMIT)
    assert consume_quota(other_user, LIMIT)


def test_quota_resets_every_day(user):
    ChatUsage.objects.create(user=user, day=timezone.localdate() - timedelta(days=1), count=LIMIT)
    assert consume_quota(user, LIMIT)


@pytest.mark.parametrize("limit", [0, -1])
def test_non_positive_limit_blocks_everything(user, limit):
    assert not consume_quota(user, limit)


def test_usage_is_deleted_with_the_account():
    member = f.make_user()
    consume_quota(member, LIMIT)
    member.delete()
    assert not ChatUsage.objects.exists()


class TestWeeklyLimit:
    def test_weekly_limit_applies_across_days_and_is_not_charged_when_refused(self, user):
        today = timezone.localdate()
        for days_ago in (1, 2):
            ChatUsage.objects.create(user=user, day=today - timedelta(days=days_ago), count=LIMIT)
        assert [consume_quota(user, LIMIT, weekly_limit=8) for _ in range(3)] == [True, True, False]
        assert ChatUsage.objects.get(user=user, day=today).count == 2

    def test_usage_older_than_seven_days_is_forgotten(self, user):
        ChatUsage.objects.create(user=user, day=timezone.localdate() - timedelta(days=7), count=50)
        assert consume_quota(user, LIMIT, weekly_limit=1)

    def test_weekly_limit_is_per_scope(self, user):
        ChatUsage.objects.create(user=user, day=timezone.localdate(), scope="label", count=2)
        assert consume_quota(user, LIMIT, weekly_limit=1)
