"""Domain entities. Pure Python: no Qt, no SQL."""

from dataclasses import dataclass
from datetime import date, timedelta
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
    # e.g. "Revolut card", "PayPal". Free text; the list can be filtered by it.
    payment_method: str = ""
    # Minimum term: the contract ends on contract_end_date and must be cancelled
    # notice_days before that, or it renews. Both optional.
    contract_end_date: date | None = None
    notice_days: int = 0
    # Payments between paused_from and paused_until (inclusive) are skipped.
    paused_from: date | None = None
    paused_until: date | None = None
    # Introductory price charged until promo_until (inclusive), then `price`.
    promo_price: Decimal | None = None
    promo_until: date | None = None
    id: int | None = None

    def is_trial(self, today: date) -> bool:
        return self.trial_end_date is not None and today <= self.trial_end_date

    def is_paused_on(self, day: date) -> bool:
        return (
            self.paused_from is not None
            and self.paused_until is not None
            and self.paused_from <= day <= self.paused_until
        )

    def has_promo_on(self, day: date) -> bool:
        return self.promo_price is not None and self.promo_until is not None and day <= self.promo_until

    @property
    def cancel_by_date(self) -> date | None:
        """Last day to cancel before the contract renews, if there is a contract end."""
        if self.contract_end_date is None:
            return None
        return self.contract_end_date - timedelta(days=self.notice_days)

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
