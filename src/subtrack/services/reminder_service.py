"""Decides which reminders are due. Showing them is the tray icon's job."""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from subtrack.data.reminder_repository import ReminderRepository
from subtrack.data.settings_repository import SettingsRepository
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain import billing
from subtrack.domain.models import Subscription


class ReminderKind(Enum):
    PAYMENT = "payment"
    TRIAL_ENDING = "trial_ending"


def _when(due: date, today: date) -> str:
    days = (due - today).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"on {due.strftime('%d %b')} (in {days} days)"


@dataclass(frozen=True)
class Reminder:
    kind: ReminderKind
    subscription: Subscription
    due_date: date

    def title(self) -> str:
        if self.kind is ReminderKind.TRIAL_ENDING:
            return f"{self.subscription.name}: free trial ending"
        return f"{self.subscription.name}: payment coming up"

    def message(self, today: date) -> str:
        sub = self.subscription
        price = f"{sub.price:.2f} {sub.currency.value}"
        if self.kind is ReminderKind.TRIAL_ENDING:
            return f"The free trial ends {_when(self.due_date, today)}. Cancel before then to avoid paying {price}."
        hint = " You marked it as rarely used." if sub.rarely_used else ""
        return f"{price} will be charged {_when(self.due_date, today)}.{hint}"


class ReminderService:
    def __init__(
        self,
        subscriptions: SubscriptionRepository,
        reminders: ReminderRepository,
        settings: SettingsRepository,
    ):
        self._subscriptions = subscriptions
        self._reminders = reminders
        self._settings = settings

    def days_before(self) -> int:
        return int(self._settings.get("reminder_days_before", "3"))

    def due_reminders(self, today: date) -> list[Reminder]:
        """Payments and trial ends within the reminder window that were not shown yet."""
        window_end = today + timedelta(days=self.days_before())
        due: list[Reminder] = []
        for sub in self._subscriptions.list():
            trial_end = sub.trial_end_date
            if trial_end is not None and today <= trial_end <= window_end:
                due.append(Reminder(ReminderKind.TRIAL_ENDING, sub, trial_end))
            payment = billing.next_payment_date(sub, today)
            if payment <= window_end:
                due.append(Reminder(ReminderKind.PAYMENT, sub, payment))
        return [
            r
            for r in sorted(due, key=lambda r: r.due_date)
            if not self._reminders.was_shown(r.subscription.id, r.kind.value, r.due_date)
        ]

    def mark_shown(self, reminder: Reminder) -> None:
        self._reminders.mark_shown(reminder.subscription.id, reminder.kind.value, reminder.due_date)
