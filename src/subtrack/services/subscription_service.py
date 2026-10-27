"""Use cases for managing subscriptions: validation + persistence."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain import billing
from subtrack.domain.models import Subscription


class ValidationError(ValueError):
    """Raised when a subscription has invalid data. The message is user-facing."""


@dataclass(frozen=True)
class SubscriptionRow:
    """A subscription plus the values the UI shows but that are not stored."""

    subscription: Subscription
    next_payment: date
    monthly_cost: Decimal
    in_trial: bool


class SubscriptionService:
    def __init__(self, repository: SubscriptionRepository, today=date.today):
        self._repo = repository
        self._today = today  # injectable so tests can fix the date

    def list_rows(self, include_inactive: bool = False) -> list[SubscriptionRow]:
        today = self._today()
        return [
            SubscriptionRow(
                subscription=sub,
                next_payment=billing.next_payment_date(sub, today),
                monthly_cost=billing.monthly_cost(sub),
                in_trial=sub.is_trial(today),
            )
            for sub in self._repo.list(include_inactive)
        ]

    def get(self, sub_id: int) -> Subscription | None:
        return self._repo.get(sub_id)

    def add(self, sub: Subscription) -> Subscription:
        self.validate(sub)
        return self._repo.insert(sub)

    def update(self, sub: Subscription) -> None:
        self.validate(sub)
        self._repo.update(sub)

    def cancel(self, sub_id: int) -> None:
        """Mark as inactive; it stays in the database as history."""
        sub = self._repo.get(sub_id)
        if sub is None:
            return
        sub.active = False
        self._repo.update(sub)

    def delete(self, sub_id: int) -> None:
        self._repo.delete(sub_id)

    @staticmethod
    def validate(sub: Subscription) -> None:
        """Raise ValidationError if invalid. Also normalises the name (strips spaces)."""
        sub.name = sub.name.strip()
        if not sub.name:
            raise ValidationError("Name is required.")
        if len(sub.name) > 100:
            raise ValidationError("Name must be at most 100 characters.")
        if sub.price < 0:
            raise ValidationError("Price cannot be negative.")
        if sub.price > Decimal("1000000"):
            raise ValidationError("Price is too large.")
