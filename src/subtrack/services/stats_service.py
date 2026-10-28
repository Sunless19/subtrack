"""Aggregated numbers for the dashboard and the list, all in the base currency.

Past amounts use the price history (and introductory prices), so a price rise
does not change what was spent before it. Cancelled subscriptions are left out:
their cancellation date is not stored, so their past spending is unknown.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain import billing
from subtrack.domain.models import Category, Subscription
from subtrack.services.currency_service import CurrencyService


@dataclass(frozen=True)
class UpcomingPayment:
    due_date: date
    subscription: Subscription
    amount_in_base: Decimal


@dataclass(frozen=True)
class MonthTotal:
    month: date  # first day of the month
    amount: Decimal
    is_forecast: bool  # True for the current month onwards


def _month_start(day: date) -> date:
    return day.replace(day=1)


class StatsService:
    def __init__(self, repository: SubscriptionRepository, currency: CurrencyService, today=date.today):
        self._repo = repository
        self._currency = currency
        self._today = today

    def monthly_total(self) -> Decimal:
        today = self._today()
        return sum(
            (self._currency.to_base(billing.monthly_cost(s, on=today), s.currency) for s in self._repo.list()),
            Decimal("0.00"),
        )

    def yearly_total(self) -> Decimal:
        today = self._today()
        return sum(
            (self._currency.to_base(billing.yearly_cost(s, on=today), s.currency) for s in self._repo.list()),
            Decimal("0.00"),
        )

    def monthly_total_by_category(self) -> dict[Category, Decimal]:
        """Only categories that have at least one active subscription, largest first."""
        today = self._today()
        totals: dict[Category, Decimal] = {}
        for sub in self._repo.list():
            amount = self._currency.to_base(billing.monthly_cost(sub, on=today), sub.currency)
            totals[sub.category] = totals.get(sub.category, Decimal(0)) + amount
        return dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))

    def upcoming_payments(self, today: date, days: int = 30) -> list[UpcomingPayment]:
        """Every payment in [today, today + days], sorted by date."""
        end = today + timedelta(days=days)
        history = self._repo.price_changes()
        payments = []
        for sub in self._repo.list():
            for due in billing.payment_dates(sub, today, end):
                share, currency = billing.share_on(sub, due, history.get(sub.id, ()))
                payments.append(UpcomingPayment(due, sub, self._currency.to_base(share, currency)))
        payments.sort(key=lambda p: (p.due_date, p.subscription.name.lower()))
        return payments

    def spent_so_far(self) -> dict[int, Decimal]:
        """Subscription id -> the user's share of every payment up to today."""
        today = self._today()
        history = self._repo.price_changes()
        totals = {}
        for sub in self._repo.list():
            total = Decimal("0.00")
            for due in billing.payment_dates(sub, sub.first_payment_date, today):
                share, currency = billing.share_on(sub, due, history.get(sub.id, ()))
                total += self._currency.to_base(share, currency)
            totals[sub.id] = total
        return totals

    def monthly_spending(self, months_back: int = 12, months_ahead: int = 12) -> list[MonthTotal]:
        """Spending per calendar month: `months_back` past months, then the current month
        and the following ones as a forecast (`months_ahead` months in total)."""
        today = self._today()
        current = _month_start(today)
        first = billing.add_months(current, -months_back)
        end = billing.add_months(current, months_ahead) - timedelta(days=1)
        history = self._repo.price_changes()
        buckets = {billing.add_months(first, i): Decimal("0.00") for i in range(months_back + months_ahead)}
        for sub in self._repo.list():
            for due in billing.payment_dates(sub, max(first, sub.first_payment_date), end):
                share, currency = billing.share_on(sub, due, history.get(sub.id, ()))
                buckets[_month_start(due)] += self._currency.to_base(share, currency)
        return [MonthTotal(month, amount, month >= current) for month, amount in buckets.items()]
