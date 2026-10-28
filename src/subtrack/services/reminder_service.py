"""Decides which reminders are due, and handles snoozing and marking payments paid.

Showing reminders is the notifier's job (ui/notifier.py).

Each payment can produce two reminders: one a few days early (PAYMENT_SOON) and
one on the day itself (PAYMENT_DUE). A free trial produces TRIAL_ENDING. Each
reminder is shown once, unless the user snoozes it, in which case it comes back
when the snooze runs out. Marking a payment as paid silences its reminders.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum

from subtrack.data.payment_repository import PaymentRepository
from subtrack.data.reminder_repository import ReminderRepository, ReminderState
from subtrack.data.settings_repository import SettingsRepository
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain import billing
from subtrack.domain.models import Subscription

TOMORROW_AT = time(9, 0)  # "Remind me tomorrow" fires at this time


class ReminderKind(Enum):
    PAYMENT_SOON = "payment"  # value kept from v0.1 so existing rows still match
    PAYMENT_DUE = "payment_due"
    TRIAL_ENDING = "trial_ending"

    @property
    def is_payment(self) -> bool:
        return self is not ReminderKind.TRIAL_ENDING


def _when(due: date, today: date) -> str:
    days = (due - today).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"on {due.strftime('%a %d %b')} (in {days} days)"


@dataclass(frozen=True)
class Reminder:
    kind: ReminderKind
    subscription: Subscription
    due_date: date

    def title(self) -> str:
        name = self.subscription.name
        if self.kind is ReminderKind.TRIAL_ENDING:
            return f"{name}: free trial ending"
        if self.kind is ReminderKind.PAYMENT_DUE:
            return f"{name}: payment due today"
        return f"{name}: payment coming up"

    def message(self, today: date) -> str:
        sub = self.subscription
        price = f"{sub.price:.2f} {sub.currency.value}"
        if self.kind is ReminderKind.TRIAL_ENDING:
            return f"The free trial ends {_when(self.due_date, today)}. Cancel before then to avoid paying {price}."
        hint = " You marked it as rarely used." if sub.rarely_used else ""
        return f"{price} will be charged {_when(self.due_date, today)}.{hint}"


class TimelineStatus(Enum):
    PAID = "Paid"
    SNOOZED = "Snoozed"
    REMINDED = "Reminded"
    DUE_TODAY = "Due today"
    UPCOMING = "Upcoming"
    NOT_MARKED_PAID = "Not marked as paid"
    TRIAL_ENDED = "Trial ended"


@dataclass(frozen=True)
class TimelineEntry:
    """One payment or trial end, for the Reminders tab."""

    is_trial_end: bool
    subscription: Subscription
    date: date
    status: TimelineStatus
    detail: str = ""  # e.g. "until Tue 28 Oct 09:00", "on 27 Oct 10:15"

    @property
    def can_mark_paid(self) -> bool:
        return not self.is_trial_end and self.status is not TimelineStatus.PAID


class ReminderService:
    def __init__(
        self,
        subscriptions: SubscriptionRepository,
        reminders: ReminderRepository,
        settings: SettingsRepository,
        payments: PaymentRepository,
    ):
        self._subscriptions = subscriptions
        self._reminders = reminders
        self._settings = settings
        self._payments = payments

    def days_before(self) -> int:
        return int(self._settings.get("reminder_days_before", "3"))

    # ---- what to show now ------------------------------------------------

    def due_reminders(self, now: datetime) -> list[Reminder]:
        """Reminders to show right now: not shown yet, or snoozed until a time that has passed."""
        today = now.date()
        window_end = today + timedelta(days=self.days_before())
        states = self._reminders.all_states()
        paid = self._payments.paid()

        candidates: list[Reminder] = []
        for sub in self._subscriptions.list():
            trial_end = sub.trial_end_date
            if trial_end is not None and today <= trial_end <= window_end:
                candidates.append(Reminder(ReminderKind.TRIAL_ENDING, sub, trial_end))
            payment = billing.next_payment_date(sub, today)
            if (sub.id, payment) in paid:
                continue
            if payment == today:
                candidates.append(Reminder(ReminderKind.PAYMENT_DUE, sub, payment))
            elif payment <= window_end:
                candidates.append(Reminder(ReminderKind.PAYMENT_SOON, sub, payment))

        due = []
        for reminder in candidates:
            state = states.get((reminder.subscription.id, reminder.kind.value, reminder.due_date))
            snooze_over = state is not None and state.snoozed_until is not None and state.snoozed_until <= now
            if state is None or snooze_over:
                due.append(reminder)
        return sorted(due, key=lambda r: (r.due_date, r.subscription.name.lower()))

    def mark_shown(self, reminder: Reminder, now: datetime) -> None:
        self._reminders.mark_shown(reminder.subscription.id, reminder.kind.value, reminder.due_date, now)

    # ---- actions from notification buttons and the Reminders tab ----------

    def snooze(self, subscription_id: int, kind: ReminderKind, due_date: date, until: datetime) -> None:
        self._reminders.snooze(subscription_id, kind.value, due_date, until)

    @staticmethod
    def snooze_target(option: str, now: datetime) -> datetime:
        """'1h' -> an hour from now; 'tomorrow' -> tomorrow at 09:00."""
        if option == "1h":
            return now.replace(microsecond=0) + timedelta(hours=1)
        if option == "tomorrow":
            return datetime.combine(now.date() + timedelta(days=1), TOMORROW_AT)
        raise ValueError(f"unknown snooze option {option!r}")

    def mark_paid(self, subscription_id: int, due_date: date, now: datetime) -> None:
        self._payments.mark_paid(subscription_id, due_date, now)

    def unmark_paid(self, subscription_id: int, due_date: date) -> None:
        self._payments.unmark_paid(subscription_id, due_date)

    # ---- Reminders tab -----------------------------------------------------

    def timeline(self, now: datetime, days_back: int = 30, days_ahead: int = 30) -> list[TimelineEntry]:
        """Every payment and trial end from days_back ago to days_ahead from now, oldest first."""
        today = now.date()
        start, end = today - timedelta(days=days_back), today + timedelta(days=days_ahead)
        states = self._reminders.all_states()
        paid = self._payments.paid()
        entries: list[TimelineEntry] = []

        for sub in self._subscriptions.list():
            due = billing.next_payment_date(sub, start)
            while due <= end:
                entries.append(self._payment_entry(sub, due, today, now, states, paid))
                due = billing.next_payment_date(sub, due + timedelta(days=1))

            trial_end = sub.trial_end_date
            if trial_end is not None and start <= trial_end <= end:
                state = states.get((sub.id, ReminderKind.TRIAL_ENDING.value, trial_end))
                if trial_end < today:
                    status, detail = TimelineStatus.TRIAL_ENDED, ""
                else:
                    status, detail = self._reminder_status(state, now) or (TimelineStatus.UPCOMING, "")
                entries.append(TimelineEntry(True, sub, trial_end, status, detail))

        entries.sort(key=lambda e: (e.date, e.subscription.name.lower(), e.is_trial_end))
        return entries

    def _payment_entry(self, sub, due, today, now, states, paid) -> TimelineEntry:
        paid_at = paid.get((sub.id, due))
        if paid_at is not None:
            return TimelineEntry(False, sub, due, TimelineStatus.PAID, f"on {paid_at:%d %b %H:%M}")
        if due < today:
            return TimelineEntry(False, sub, due, TimelineStatus.NOT_MARKED_PAID)
        # The latest thing that happened to either of this payment's reminders.
        found = [
            self._reminder_status(states.get((sub.id, kind.value, due)), now)
            for kind in (ReminderKind.PAYMENT_DUE, ReminderKind.PAYMENT_SOON)
        ]
        found = [f for f in found if f]
        if found:
            status, detail = found[0]
            return TimelineEntry(False, sub, due, status, detail)
        status = TimelineStatus.DUE_TODAY if due == today else TimelineStatus.UPCOMING
        return TimelineEntry(False, sub, due, status)

    @staticmethod
    def _reminder_status(state: ReminderState | None, now: datetime):
        if state is None:
            return None
        if state.snoozed_until is not None and state.snoozed_until > now:
            return TimelineStatus.SNOOZED, f"until {state.snoozed_until:%a %d %b %H:%M}"
        if state.shown_at is not None:
            return TimelineStatus.REMINDED, f"on {state.shown_at:%d %b %H:%M}"
        return None
