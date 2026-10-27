"""Billing calculations: payment dates and normalised costs.

Payment dates are always derived from the first payment date, never stored,
so nothing has to be "advanced" in the database after a payment happens.
"""

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from subtrack.domain.models import BillingCycle, Subscription

_MONTHS_PER_CYCLE = {
    BillingCycle.MONTHLY: 1,
    BillingCycle.QUARTERLY: 3,
    BillingCycle.YEARLY: 12,
}

# How many times per year each cycle is charged.
_CHARGES_PER_YEAR = {
    BillingCycle.WEEKLY: Decimal(52),
    BillingCycle.MONTHLY: Decimal(12),
    BillingCycle.QUARTERLY: Decimal(4),
    BillingCycle.YEARLY: Decimal(1),
}

_CENT = Decimal("0.01")


def add_months(start: date, months: int) -> date:
    """Add months to a date, clamping to the last day of shorter months.

    31 Jan + 1 month -> 28/29 Feb.
    """
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


def nth_payment_date(first: date, cycle: BillingCycle, n: int) -> date:
    """Date of the n-th payment, where n = 0 is the first payment.

    Always computed from the first date so that the original day of the month
    is kept (31 Jan -> 28 Feb -> 31 Mar, not 28 Mar).
    """
    if cycle is BillingCycle.WEEKLY:
        return first + timedelta(weeks=n)
    return add_months(first, n * _MONTHS_PER_CYCLE[cycle])


def next_payment_date(sub: Subscription, today: date) -> date:
    """First payment date on or after today.

    Payments during a free trial are skipped: the first charge is the first
    payment date after the trial ends.
    """
    earliest = today
    if sub.trial_end_date is not None and sub.trial_end_date >= earliest:
        earliest = sub.trial_end_date + timedelta(days=1)
    if sub.first_payment_date >= earliest:
        return sub.first_payment_date

    # Jump close to the answer instead of iterating from the first date.
    if sub.billing_cycle is BillingCycle.WEEKLY:
        n = (earliest - sub.first_payment_date).days // 7
    else:
        months_between = (earliest.year - sub.first_payment_date.year) * 12 + (
            earliest.month - sub.first_payment_date.month
        )
        n = max(months_between // _MONTHS_PER_CYCLE[sub.billing_cycle], 0)

    while nth_payment_date(sub.first_payment_date, sub.billing_cycle, n) < earliest:
        n += 1
    return nth_payment_date(sub.first_payment_date, sub.billing_cycle, n)


def yearly_cost(sub: Subscription) -> Decimal:
    """Cost over one year, in the subscription's own currency."""
    return (sub.price * _CHARGES_PER_YEAR[sub.billing_cycle]).quantize(_CENT, ROUND_HALF_UP)


def monthly_cost(sub: Subscription) -> Decimal:
    """Average cost per month, in the subscription's own currency."""
    return (sub.price * _CHARGES_PER_YEAR[sub.billing_cycle] / 12).quantize(
        _CENT, ROUND_HALF_UP
    )
