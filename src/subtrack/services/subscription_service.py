"""Use cases for managing subscriptions: validation + persistence."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain import billing
from subtrack.domain.models import PriceChange, Subscription


class ValidationError(ValueError):
    """Raised when a subscription has invalid data. The message is user-facing."""


@dataclass(frozen=True)
class SubscriptionRow:
    """A subscription plus the values the UI shows but that are not stored."""

    subscription: Subscription
    next_payment: date
    monthly_cost: Decimal  # the user's share
    in_trial: bool
    price_history: tuple[PriceChange, ...] = ()

    @property
    def price_change_percent(self) -> Decimal | None:
        """Change from the first recorded price to now, e.g. 25.0 for +25%. None if unknown."""
        if not self.price_history:
            return None
        first = self.price_history[0]
        if first.old_currency is not self.subscription.currency or first.old_price == 0:
            return None
        change = (self.subscription.price - first.old_price) / first.old_price * 100
        return change.quantize(Decimal("0.1"))


class SubscriptionService:
    def __init__(self, repository: SubscriptionRepository, today=date.today):
        self._repo = repository
        self._today = today  # injectable so tests can fix the date

    def list_rows(self, include_inactive: bool = False) -> list[SubscriptionRow]:
        today = self._today()
        history = self._repo.price_changes()
        return [
            SubscriptionRow(
                subscription=sub,
                next_payment=billing.next_payment_date(sub, today),
                monthly_cost=billing.monthly_cost(sub),
                in_trial=sub.is_trial(today),
                price_history=tuple(history.get(sub.id, ())),
            )
            for sub in self._repo.list(include_inactive)
        ]

    def get(self, sub_id: int) -> Subscription | None:
        return self._repo.get(sub_id)

    def price_history(self, sub_id: int) -> list[PriceChange]:
        return self._repo.price_changes(sub_id).get(sub_id, [])

    def add(self, sub: Subscription) -> Subscription:
        self.validate(sub)
        return self._repo.insert(sub)

    def update(self, sub: Subscription) -> None:
        """Save changes. A changed price or currency is recorded in the price history."""
        self.validate(sub)
        old = self._repo.get(sub.id) if sub.id is not None else None
        self._repo.update(sub)
        if old is not None and (old.price, old.currency) != (sub.price, sub.currency):
            self._repo.add_price_change(
                sub.id, PriceChange(self._today(), old.price, old.currency, sub.price, sub.currency)
            )

    def cancel(self, sub_id: int) -> None:
        """Mark as inactive; it stays in the database as history."""
        sub = self._repo.get(sub_id)
        if sub is None:
            return
        sub.active = False
        self._repo.update(sub)

    def reactivate(self, sub_id: int) -> None:
        sub = self._repo.get(sub_id)
        if sub is None:
            return
        sub.active = True
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
        if not 1 <= sub.shared_with <= 50:
            raise ValidationError("A subscription can be shared by 1 to 50 people.")
