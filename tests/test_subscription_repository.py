from datetime import date
from decimal import Decimal

import pytest

from subtrack.data.database import MIGRATIONS, Database
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain.models import BillingCycle, Category, Currency, Subscription


@pytest.fixture
def repo():
    db = Database(":memory:")
    yield SubscriptionRepository(db)
    db.close()


def netflix(**overrides):
    values = dict(
        name="Netflix",
        price=Decimal("49.99"),
        currency=Currency.RON,
        billing_cycle=BillingCycle.MONTHLY,
        first_payment_date=date(2026, 3, 5),
        category=Category.STREAMING,
    )
    values.update(overrides)
    return Subscription(**values)


def test_migrations_set_schema_version():
    db = Database(":memory:")
    assert db.schema_version == len(MIGRATIONS)
    db.close()


def test_insert_and_get_round_trip(repo):
    sub = repo.insert(netflix(trial_end_date=date(2026, 4, 1), rarely_used=True, notes="family plan"))
    assert sub.id is not None
    assert repo.get(sub.id) == sub


def test_update(repo):
    sub = repo.insert(netflix())
    sub.price = Decimal("59.99")
    sub.currency = Currency.EUR
    repo.update(sub)
    assert repo.get(sub.id).price == Decimal("59.99")
    assert repo.get(sub.id).currency is Currency.EUR


def test_list_hides_inactive_and_sorts_by_name(repo):
    repo.insert(netflix(name="spotify"))
    repo.insert(netflix(name="Apple TV", active=False))
    repo.insert(netflix(name="Netflix"))
    assert [s.name for s in repo.list()] == ["Netflix", "spotify"]
    assert [s.name for s in repo.list(include_inactive=True)] == ["Apple TV", "Netflix", "spotify"]


def test_delete(repo):
    sub = repo.insert(netflix())
    repo.delete(sub.id)
    assert repo.get(sub.id) is None
