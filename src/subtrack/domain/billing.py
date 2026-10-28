"""Billing calculations: payment dates and normalised costs.

Payment dates are always derived from the first payment date, never stored,
so nothing has to be "advanced" in the database after a payment happens.
"""

import calendar
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from subtrack.domain.models import BillingCycle, Currency, PriceChange, Subscription

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
    payment date after the trial ends. Payments while paused are skipped too.
    """
    earliest = today
    if sub.trial_end_date is not None and sub.trial_end_date >= earliest:
        earliest = sub.trial_end_date + timedelta(days=1)
    due = _scheduled_on_or_after(sub, earliest)
    if sub.is_paused_on(due):
        due = _scheduled_on_or_after(sub, sub.paused_until + timedelta(days=1))
    return due


def _scheduled_on_or_after(sub: Subscription, earliest: date) -> date:
    """First date of the plain billing schedule on or after `earliest`."""
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


def payment_dates(sub: Subscription, start: date, end: date) -> list[date]:
    """Every payment date in [start, end], skipping trial and paused periods."""
    dates = []
    due = next_payment_date(sub, start)
    while due <= end:
        dates.append(due)
        due = next_payment_date(sub, due + timedelta(days=1))
    return dates


def amount_on(sub: Subscription, day: date, history: Sequence[PriceChange] = ()) -> tuple[Decimal, Currency]:
    """Full price charged on `day` (before splitting), and its currency.

    An introductory (promo) price applies up to its end date. Otherwise the price
    history decides what the price was on that day; without history it is `price`.
    """
    if sub.has_promo_on(day):
        return sub.promo_price, sub.currency
    for change in reversed(history):  # history is oldest first
        if change.changed_on <= day:
            return change.new_price, change.new_currency
    if history:
        return history[0].old_price, history[0].old_currency
    return sub.price, sub.currency


def share_on(sub: Subscription, day: date, history: Sequence[PriceChange] = ()) -> tuple[Decimal, Currency]:
    """The user's part of the payment on `day`."""
    amount, currency = amount_on(sub, day, history)
    return (amount / sub.shared_with).quantize(_CENT, ROUND_HALF_UP), currency


def _current_price(sub: Subscription, on: date | None) -> Decimal:
    return sub.promo_price if on is not None and sub.has_promo_on(on) else sub.price


def yearly_cost(sub: Subscription, on: date | None = None) -> Decimal:
    """The user's cost over one year (their share if shared), in the subscription's currency.

    With `on`, a promo price running on that day is used instead of the regular price.
    """
    price = _current_price(sub, on)
    return (price * _CHARGES_PER_YEAR[sub.billing_cycle] / sub.shared_with).quantize(_CENT, ROUND_HALF_UP)


def monthly_cost(sub: Subscription, on: date | None = None) -> Decimal:
    """The user's average cost per month (their share if shared), in the subscription's currency.

    With `on`, a promo price running on that day is used instead of the regular price.
    """
    price = _current_price(sub, on)
    return (price * _CHARGES_PER_YEAR[sub.billing_cycle] / 12 / sub.shared_with).quantize(
        _CENT, ROUND_HALF_UP
    )
