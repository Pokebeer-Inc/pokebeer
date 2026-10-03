"""Fixtures communes aux tests de l'admin."""
import pytest

from tests import factories as f


@pytest.fixture
def superuser(db):
    return f.make_user(username="root", is_superuser=True, groups=("Staff",))


@pytest.fixture
def staff(db):
    return f.make_user(username="moderator", groups=("Staff",))
