"""Domain entities. Pure Python: no Qt, no SQL."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
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
    id: int | None = None

    def is_trial(self, today: date) -> bool:
        return self.trial_end_date is not None and today <= self.trial_end_date
