from datetime import date
from decimal import Decimal

from subtrack.domain import billing
from subtrack.domain.models import BillingCycle, Currency, Subscription


def make(cycle=BillingCycle.MONTHLY, first=date(2026, 1, 31), price="10.00", trial=None):
    return Subscription(
        name="Test",
        price=Decimal(price),
        currency=Currency.RON,
        billing_cycle=cycle,
        first_payment_date=first,
        trial_end_date=trial,
    )


def test_add_months_clamps_to_end_of_month():
    assert billing.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert billing.add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert billing.add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_monthly_keeps_original_day_after_short_month():
    sub = make(first=date(2026, 1, 31))
    assert billing.next_payment_date(sub, date(2026, 2, 1)) == date(2026, 2, 28)
    assert billing.next_payment_date(sub, date(2026, 3, 1)) == date(2026, 3, 31)


def test_payment_today_counts_as_next():
    sub = make(first=date(2026, 1, 15))
    assert billing.next_payment_date(sub, date(2026, 10, 15)) == date(2026, 10, 15)


def test_first_payment_in_future():
    sub = make(first=date(2027, 5, 1))
    assert billing.next_payment_date(sub, date(2026, 10, 27)) == date(2027, 5, 1)


def test_weekly_quarterly_yearly():
    today = date(2026, 10, 27)
    assert billing.next_payment_date(make(BillingCycle.WEEKLY, date(2026, 10, 1)), today) == date(2026, 10, 29)
    assert billing.next_payment_date(make(BillingCycle.QUARTERLY, date(2026, 1, 10)), today) == date(2027, 1, 10)
    assert billing.next_payment_date(make(BillingCycle.YEARLY, date(2024, 2, 29)), today) == date(2027, 2, 28)


def test_trial_skips_payments_until_it_ends():
    sub = make(first=date(2026, 10, 1), trial=date(2026, 11, 15))
    assert billing.next_payment_date(sub, date(2026, 10, 27)) == date(2026, 12, 1)


def test_costs_are_normalised():
    assert billing.monthly_cost(make(BillingCycle.YEARLY, price="120")) == Decimal("10.00")
    assert billing.monthly_cost(make(BillingCycle.WEEKLY, price="10")) == Decimal("43.33")
    assert billing.yearly_cost(make(BillingCycle.QUARTERLY, price="15.50")) == Decimal("62.00")
