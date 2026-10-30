"""Request and response shapes for the HTTP API.

Money is sent as decimal strings ("49.99"), never floats, so nothing is lost
to rounding. Dates are ISO strings ("2026-10-30").
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from subtrack.domain.models import BillingCycle, Category, Currency, Subscription
from subtrack.services.reminder_service import Reminder, TimelineEntry
from subtrack.services.subscription_service import SubscriptionRow


class SubscriptionIn(BaseModel):
    """What a client sends to create or replace a subscription."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(examples=["Netflix"])
    price: Decimal = Field(examples=["49.99"])
    currency: Currency
    billing_cycle: BillingCycle
    first_payment_date: date
    category: Category = Category.OTHER
    trial_end_date: date | None = None
    rarely_used: bool = False
    active: bool = True
    notes: str = ""
    shared_with: int = 1
    payment_method: str = ""
    contract_end_date: date | None = None
    notice_days: int = 0
    paused_from: date | None = None
    paused_until: date | None = None
    promo_price: Decimal | None = None
    promo_until: date | None = None

    def to_domain(self, sub_id: int | None = None) -> Subscription:
        return Subscription(id=sub_id, **self.model_dump())


class PriceChangeOut(BaseModel):
    changed_on: date
    old_price: Decimal
    old_currency: Currency
    new_price: Decimal
    new_currency: Currency


class SubscriptionOut(SubscriptionIn):
    """A stored subscription plus values the API calculates."""

    model_config = ConfigDict(extra="ignore")

    id: int
    next_payment: date
    monthly_cost: Decimal = Field(description="The user's share per month, in the subscription's currency")
    my_share: Decimal = Field(description="The user's part of one payment")
    in_trial: bool
    promo_active: bool
    paused: bool
    cancel_by: date | None
    price_change_percent: Decimal | None
    price_history: list[PriceChangeOut]

    @classmethod
    def from_row(cls, row: SubscriptionRow) -> "SubscriptionOut":
        sub = row.subscription
        fields = {k: v for k, v in vars(sub).items() if k != "id"}
        return cls(
            id=sub.id,
            **fields,
            next_payment=row.next_payment,
            monthly_cost=row.monthly_cost,
            my_share=sub.my_share,
            in_trial=row.in_trial,
            promo_active=row.promo_active,
            paused=row.paused,
            cancel_by=row.cancel_by,
            price_change_percent=row.price_change_percent,
            price_history=[PriceChangeOut(**vars(c)) for c in row.price_history],
        )


class Summary(BaseModel):
    base_currency: Currency
    monthly_total: Decimal
    yearly_total: Decimal
    active_subscriptions: int


class CategoryTotal(BaseModel):
    category: Category
    monthly: Decimal


class UpcomingPaymentOut(BaseModel):
    due_date: date
    subscription_id: int
    name: str
    amount: Decimal = Field(description="The user's share, in the base currency")


class MonthTotalOut(BaseModel):
    month: date
    amount: Decimal
    is_forecast: bool


class SpentOut(BaseModel):
    subscription_id: int
    name: str
    spent: Decimal = Field(description="In the base currency")


class ReminderOut(BaseModel):
    kind: str
    subscription_id: int
    name: str
    due_date: date
    title: str
    message: str

    @classmethod
    def from_reminder(cls, reminder: Reminder, today: date) -> "ReminderOut":
        return cls(
            kind=reminder.kind.value,
            subscription_id=reminder.subscription.id,
            name=reminder.subscription.name,
            due_date=reminder.due_date,
            title=reminder.title(),
            message=reminder.message(today),
        )


class TimelineEntryOut(BaseModel):
    event: str
    subscription_id: int
    name: str
    date: date
    status: str
    detail: str
    can_mark_paid: bool

    @classmethod
    def from_entry(cls, entry: TimelineEntry) -> "TimelineEntryOut":
        return cls(
            event=entry.event.value,
            subscription_id=entry.subscription.id,
            name=entry.subscription.name,
            date=entry.date,
            status=entry.status.value,
            detail=entry.detail,
            can_mark_paid=entry.can_mark_paid,
        )


class SnoozeIn(BaseModel):
    subscription_id: int
    kind: str = Field(examples=["payment_due"])
    due_date: date
    until: datetime | None = Field(None, description="Exact time; or use 'option'")
    option: str | None = Field(None, description="'1h' or 'tomorrow'")


class SettingsOut(BaseModel):
    base_currency: Currency
    rates_in_ron: dict[Currency, Decimal]
    rates_updated_on: date | None
    reminder_days_before: int


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_currency: Currency | None = None
    rates_in_ron: dict[Currency, Decimal] | None = None
    reminder_days_before: int | None = Field(None, ge=0, le=30)


class TemplateOut(BaseModel):
    name: str
    category: Category
    billing_cycle: BillingCycle


class ImportResultOut(BaseModel):
    imported: int
    skipped_duplicates: int
