from datetime import timedelta

import pytest
from django.utils import timezone

from app.models import ChatUsage
from app.services.quota import consume_chat_quota
from tests import factories as f

pytestmark = pytest.mark.django_db

LIMIT = 3


def consume(user, times):
    return [consume_chat_quota(user, LIMIT) for _ in range(times)]


def test_allows_exactly_the_limit_then_refuses(user):
    assert consume(user, LIMIT + 2) == [True] * LIMIT + [False, False]
    assert ChatUsage.objects.get(user=user).count == LIMIT


def test_quota_is_per_user(user, other_user):
    consume(user, LIMIT)
    assert consume_chat_quota(other_user, LIMIT)


def test_quota_resets_every_day(user):
    ChatUsage.objects.create(user=user, day=timezone.localdate() - timedelta(days=1), count=LIMIT)
    assert consume_chat_quota(user, LIMIT)


@pytest.mark.parametrize("limit", [0, -1])
def test_non_positive_limit_blocks_everything(user, limit):
    assert not consume_chat_quota(user, limit)


def test_usage_is_deleted_with_the_account():
    member = f.make_user()
    consume_chat_quota(member, LIMIT)
    member.delete()
    assert not ChatUsage.objects.exists()
