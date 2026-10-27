from datetime import date
from decimal import Decimal

import pytest

from subtrack.data.database import Database
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain.models import BillingCycle, Currency, Subscription
from subtrack.services.subscription_service import SubscriptionService, ValidationError

TODAY = date(2026, 10, 27)


@pytest.fixture
def service():
    db = Database(":memory:")
    yield SubscriptionService(SubscriptionRepository(db), today=lambda: TODAY)
    db.close()


def sub(name="Spotify", price="25.99", currency=Currency.RON, cycle=BillingCycle.MONTHLY, **extra):
    return Subscription(
        name=name,
        price=Decimal(price),
        currency=currency,
        billing_cycle=cycle,
        first_payment_date=date(2026, 1, 10),
        **extra,
    )


def test_add_trims_name(service):
    added = service.add(sub(name="  Spotify  "))
    assert added.name == "Spotify"


@pytest.mark.parametrize(
    "bad, message",
    [(sub(name="   "), "Name is required"), (sub(price="-1"), "negative")],
)
def test_add_rejects_invalid(service, bad, message):
    with pytest.raises(ValidationError, match=message):
        service.add(bad)


def test_list_rows_include_next_payment_and_trial_flag(service):
    service.add(sub(trial_end_date=date(2026, 11, 5)))
    row = service.list_rows()[0]
    assert row.next_payment == date(2026, 11, 10)
    assert row.monthly_cost == Decimal("25.99")
    assert row.in_trial


def test_cancel_hides_from_list(service):
    added = service.add(sub())
    service.cancel(added.id)
    assert service.list_rows() == []
    assert len(service.list_rows(include_inactive=True)) == 1
