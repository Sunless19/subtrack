"""Aggregated numbers for the dashboard, all in the base currency."""

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


class StatsService:
    def __init__(self, repository: SubscriptionRepository, currency: CurrencyService):
        self._repo = repository
        self._currency = currency

    def monthly_total(self) -> Decimal:
        return sum(
            (self._currency.to_base(billing.monthly_cost(s), s.currency) for s in self._repo.list()),
            Decimal("0.00"),
        )

    def yearly_total(self) -> Decimal:
        return sum(
            (self._currency.to_base(billing.yearly_cost(s), s.currency) for s in self._repo.list()),
            Decimal("0.00"),
        )

    def monthly_total_by_category(self) -> dict[Category, Decimal]:
        """Only categories that have at least one active subscription, largest first."""
        totals: dict[Category, Decimal] = {}
        for sub in self._repo.list():
            amount = self._currency.to_base(billing.monthly_cost(sub), sub.currency)
            totals[sub.category] = totals.get(sub.category, Decimal(0)) + amount
        return dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))

    def upcoming_payments(self, today: date, days: int = 30) -> list[UpcomingPayment]:
        """Every payment in [today, today + days], sorted by date."""
        end = today + timedelta(days=days)
        payments = []
        for sub in self._repo.list():
            amount = self._currency.to_base(sub.price, sub.currency)
            due = billing.next_payment_date(sub, today)
            while due <= end:
                payments.append(UpcomingPayment(due, sub, amount))
                due = billing.next_payment_date(sub, due + timedelta(days=1))
        payments.sort(key=lambda p: (p.due_date, p.subscription.name.lower()))
        return payments
