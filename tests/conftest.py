from datetime import date
from decimal import Decimal

import pytest

from subtrack.data.database import Database
from subtrack.domain.models import BillingCycle, Category, Currency, Subscription


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


def make_sub(
    name="Spotify",
    price="25.99",
    currency=Currency.RON,
    cycle=BillingCycle.MONTHLY,
    first=date(2026, 1, 10),
    category=Category.MUSIC,
    **extra,
) -> Subscription:
    return Subscription(
        name=name,
        price=Decimal(price),
        currency=currency,
        billing_cycle=cycle,
        first_payment_date=first,
        category=category,
        **extra,
    )
