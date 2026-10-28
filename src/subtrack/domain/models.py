"""Domain entities. Pure Python: no Qt, no SQL."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum


class Currency(str, Enum):
    RON = "RON"
    EUR = "EUR"
    USD = "USD"


class BillingCycle(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class Category(str, Enum):
    STREAMING = "streaming"
    MUSIC = "music"
    SOFTWARE = "software"
    CLOUD = "cloud"
    GAMING = "gaming"
    UTILITIES = "utilities"
    FITNESS = "fitness"
    NEWS = "news"
    OTHER = "other"

    @property
    def label(self) -> str:
        return self.value.capitalize()


@dataclass
class Subscription:
    name: str
    price: Decimal
    currency: Currency
    billing_cycle: BillingCycle
    first_payment_date: date
    category: Category = Category.OTHER
    trial_end_date: date | None = None
    rarely_used: bool = False
    active: bool = True
    notes: str = ""
    # People splitting the cost, including the user. 1 = not shared.
    shared_with: int = 1
    id: int | None = None

    def is_trial(self, today: date) -> bool:
        return self.trial_end_date is not None and today <= self.trial_end_date

    @property
    def is_shared(self) -> bool:
        return self.shared_with > 1

    @property
    def my_share(self) -> Decimal:
        """The user's part of one payment."""
        return (self.price / self.shared_with).quantize(Decimal("0.01"), ROUND_HALF_UP)


@dataclass(frozen=True)
class PriceChange:
    changed_on: date
    old_price: Decimal
    old_currency: Currency
    new_price: Decimal
    new_currency: Currency
